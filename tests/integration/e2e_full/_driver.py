"""
_driver.py — Full-Journey E2E 测试驱动器

设计目标（对齐用户要求"完全模拟飞书消息"）：
- 用户侧：通过 `Driver.say(text)` 模拟一条飞书入站消息（走 runner.dispatch，等价于 Feishu Listener 出事件）
- 机器侧：`AccumulatingSender` 累积所有出站消息（send / send_text / update_card）
- 等待：`wait_for_file(...)`, `wait_for_bot_message(...)`, `wait_for_event(...)` 对产物/事件/消息轮询
- 运行时：复用 `xiaopaw_team.main.build_runtime`，4 角色 agent_fn + CronService + Manager Lock
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from xiaopaw_team.main import build_runtime
from xiaopaw_team.models import InboundMessage, SenderProtocol


REPO_ROOT = Path(__file__).resolve().parents[3]
SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://localhost:8029/mcp")
# 沙盒 docker-compose 挂载 ./workspace:/workspace，**不可变**。
# 所以测试必须直接使用真实 workspace/ 作为 workspace_root。
# 为防污染，Driver 在 start() 时整目录备份，stop() 时还原。
REAL_WORKSPACE = REPO_ROOT / "workspace"


def sandbox_ready() -> bool:
    """探测沙盒是否就绪；跳过所有 E2E 测试前用."""
    try:
        import urllib.request

        urllib.request.urlopen(SANDBOX_URL.replace("/mcp", ""), timeout=3)
        return True
    except Exception:
        return False


def require_env(reason_if_missing: str = "需 QWEN_API_KEY + 沙盒 8029") -> None:
    if not os.environ.get("QWEN_API_KEY"):
        pytest.skip(reason_if_missing + "（缺 QWEN_API_KEY）")
    if not sandbox_ready():
        pytest.skip(reason_if_missing + "（沙盒 http://localhost:8029/ 不可达）")


class AccumulatingSender:
    """累积所有 Bot 出站消息（send + update_card + send_text），供断言查询."""

    def __init__(self) -> None:
        self.messages: list[dict] = []  # 按时间顺序：{ts_ms, routing_key, kind, content}

    def _add(self, routing_key: str, kind: str, content: str) -> None:
        self.messages.append({
            "ts_ms": int(time.time() * 1000),
            "routing_key": routing_key,
            "kind": kind,
            "content": content,
        })
        print(f"[BOT -> {routing_key}] ({kind}) {content[:220]}")

    async def send(self, routing_key: str, content: str, root_id: str = "") -> None:
        self._add(routing_key, "send", content)

    async def send_text(self, routing_key: str, content: str, root_id: str = "") -> None:
        self._add(routing_key, "send_text", content)

    async def send_thinking(self, routing_key: str, root_id: str = "") -> str | None:
        return None

    async def update_card(self, card_msg_id: str, content: str) -> None:
        # update_card 发生时 routing_key 在调用点丢失；用特殊标记
        self._add("<update_card>", "update_card", content)


def _chmod_open(dst: Path) -> None:
    """放开沙盒 gem 用户写权限（dir 777 / file 666）."""
    for dirpath, _, filenames in os.walk(dst):
        try:
            os.chmod(dirpath, 0o777)
        except PermissionError:
            pass
        for fn in filenames:
            try:
                os.chmod(os.path.join(dirpath, fn), 0o666)
            except PermissionError:
                pass


class WorkspaceSafeguard:
    """保证测试不污染原 workspace：start 前整目录备份，stop 时完整还原.

    还原策略：
    1. 删除 workspace/ 内所有内容
    2. 从备份目录 rsync/copy 回来
    这样即使测试中 Agent 改了任何 SKILL.md / agent.md / soul.md 都能还原。
    同时 shared/projects/test-* 也会一并清理（因为它们是测试产生的 untracked 新目录）.
    """

    def __init__(self, backup_dir: Path) -> None:
        self._backup_dir = backup_dir
        self._active = False

    def capture(self) -> None:
        if self._active:
            return
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        # 用 shutil.copytree，dirs_exist_ok 允许覆盖
        if self._backup_dir.exists():
            shutil.rmtree(self._backup_dir)
        shutil.copytree(REAL_WORKSPACE, self._backup_dir, symlinks=True)
        self._active = True
        print(f"[SAFEGUARD] workspace backed up → {self._backup_dir}")

    def restore(self) -> None:
        if not self._active:
            return
        # 先删除 workspace 内容（保留 .git 等顶层无关文件如有的话——此 workspace/ 不是 git repo 根）
        if REAL_WORKSPACE.exists():
            shutil.rmtree(REAL_WORKSPACE)
        shutil.copytree(self._backup_dir, REAL_WORKSPACE, symlinks=True)
        # 清理备份
        shutil.rmtree(self._backup_dir, ignore_errors=True)
        self._active = False
        print(f"[SAFEGUARD] workspace restored from backup")


@dataclass
class DriverOptions:
    routing_key: str = "p2p:e2e-user"
    sender_id: str = "e2e-user"
    long_wait: float = 1800.0  # 30 min per stage cap
    tick: float = 5.0


class E2EDriver:
    """E2E 测试驱动器：模拟人类用户 + 观察 Bot 行为.

    workspace_root 固定为真实 REAL_WORKSPACE（因为沙盒 mount 不可变），
    但 start() 前整目录备份，stop() 时完整还原，保证测试后原仓库无污染。

    project_id 必须带 "test-" 前缀，便于识别清理。
    """

    def __init__(
        self,
        *,
        backup_dir: Path,
        data_dir: Path,
        options: DriverOptions | None = None,
    ) -> None:
        self.workspace_root = REAL_WORKSPACE  # 必须与沙盒 mount 一致
        self.data_dir = data_dir
        self.options = options or DriverOptions()
        self.sender = AccumulatingSender()
        self.runner: object | None = None
        self.cron_svc: object | None = None
        self._started = False
        self._safeguard = WorkspaceSafeguard(backup_dir)

    async def start(self) -> None:
        # 1. 备份真实 workspace/
        self._safeguard.capture()
        # 2. 清理 shared/projects/（可能有 legacy 测试残留污染 Agent 判断）
        projects_dir = self.workspace_root / "shared" / "projects"
        if projects_dir.exists():
            for p in projects_dir.iterdir():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
        projects_dir.mkdir(parents=True, exist_ok=True)
        self._start_ms = int(time.time() * 1000)
        # 3. 放开权限（沙盒 gem 用户能写）
        _chmod_open(self.workspace_root)
        # 4. 启动 runtime（agent_fn 指向真实 workspace_root）
        # 拉长 heartbeat 间隔到 10 分钟，让 E2E 测试几乎完全由"用户消息+邮件wake"驱动，
        # 不浪费 LLM 额度在 heartbeat 无事回复上
        self.runner, self.cron_svc, _ = await build_runtime(
            workspace_root=self.workspace_root,
            data_dir=self.data_dir,
            ctx_dir=self.data_dir / "ctx",
            sandbox_url=SANDBOX_URL,
            sender=self.sender,  # type: ignore[arg-type]
            heartbeat_interval_ms=600_000,  # 10 分钟
        )
        self._started = True

    async def stop(self) -> None:
        # 1. 停 CronService
        if self.cron_svc is not None:
            try:
                await self.cron_svc.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
        # 2. 无论测试成败，完整还原 workspace
        try:
            self._safeguard.restore()
        except Exception as exc:
            print(f"[SAFEGUARD ERROR] restore 失败：{exc} — 请手动从 {self._safeguard._backup_dir} 还原")
            raise

    # ── 用户侧 ────────────────────────────────────────────────────────────

    async def say(self, text: str) -> str:
        """模拟一条飞书用户消息入站."""
        assert self._started, "call start() first"
        msg_id = f"user-{int(time.time() * 1000)}"
        print(f"\n[USER -> {self.options.routing_key}] {text}\n")
        await self.runner.dispatch(InboundMessage(  # type: ignore[union-attr]
            routing_key=self.options.routing_key,
            content=text,
            msg_id=msg_id,
            root_id=msg_id,
            sender_id=self.options.sender_id,
            ts=int(time.time() * 1000),
        ))
        return msg_id

    # ── 等待条件 ──────────────────────────────────────────────────────────

    async def wait_until(
        self,
        predicate: Callable[[], bool],
        *,
        timeout: float | None = None,
        label: str = "",
    ) -> None:
        timeout = timeout or self.options.long_wait
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if predicate():
                    return
            except Exception as exc:  # noqa: BLE001
                print(f"[PREDICATE ERROR {label}] {exc}")
            await asyncio.sleep(self.options.tick)
        raise TimeoutError(f"wait_until({label or predicate}) 超时 {timeout}s")

    def list_projects(self) -> list[str]:
        """按创建时间升序返回 driver.start() 之后创建的项目."""
        base = self.workspace_root / "shared" / "projects"
        if not base.exists():
            return []
        start_ms = getattr(self, "_start_ms", 0)
        projs = [
            (p.name, p.stat().st_mtime)
            for p in base.iterdir()
            if p.is_dir() and p.stat().st_mtime * 1000 >= start_ms - 1000
        ]
        projs.sort(key=lambda x: x[1])
        return [name for name, _ in projs]

    def current_project_id(self) -> str | None:
        """返回本次 driver 运行期间创建的**最新**项目（最后 mtime）."""
        projects = self.list_projects()
        return projects[-1] if projects else None

    def proj_dir(self, project_id: str | None = None) -> Path | None:
        pid = project_id or self.current_project_id()
        if pid is None:
            return None
        return self.workspace_root / "shared" / "projects" / pid

    def file_exists(self, rel_path: str, project_id: str | None = None) -> bool:
        p = self.proj_dir(project_id)
        return bool(p and (p / rel_path).exists())

    def read_file(self, rel_path: str, project_id: str | None = None) -> str:
        p = self.proj_dir(project_id)
        if p is None:
            raise FileNotFoundError("no project yet")
        return (p / rel_path).read_text(encoding="utf-8")

    def events(self, project_id: str | None = None) -> list[dict]:
        p = self.proj_dir(project_id)
        if p is None:
            return []
        f = p / "events.jsonl"
        if not f.exists():
            return []
        out = []
        for line in f.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def has_event(self, action: str, project_id: str | None = None) -> bool:
        return any(e.get("action") == action for e in self.events(project_id))

    def has_event_matching(self, pattern: str, project_id: str | None = None) -> bool:
        rx = re.compile(pattern)
        return any(rx.match(e.get("action", "")) for e in self.events(project_id))

    def count_event(self, action: str, project_id: str | None = None) -> int:
        return sum(1 for e in self.events(project_id) if e.get("action") == action)

    def bot_said_something(self, since_ms: int = 0) -> bool:
        return any(m["ts_ms"] >= since_ms for m in self.sender.messages)

    def bot_message_contains(self, text: str, since_ms: int = 0) -> bool:
        return any(
            text in m["content"] for m in self.sender.messages if m["ts_ms"] >= since_ms
        )

    def bot_asked_for_checkpoint(self, since_ms: int = 0) -> bool:
        """启发式识别：最后一条 bot 消息看起来像 checkpoint_request."""
        recent = [m for m in self.sender.messages if m["ts_ms"] >= since_ms]
        if not recent:
            return False
        last = recent[-1]["content"]
        return any(
            kw in last
            for kw in ["同意", "批准", "确认", "checkpoint", "请回复", "approve", "是否同意"]
        )

    async def wait_for_file(self, rel_path: str, *, timeout: float | None = None) -> None:
        await self.wait_until(lambda: self.file_exists(rel_path), timeout=timeout, label=f"file:{rel_path}")

    async def wait_for_event(self, action: str, *, timeout: float | None = None) -> None:
        await self.wait_until(lambda: self.has_event(action), timeout=timeout, label=f"event:{action}")

    async def wait_for_bot_ask(self, *, timeout: float | None = None) -> int:
        """等 bot 发出下一条消息；返回此刻时间戳（可作为 since_ms 用于后续过滤）."""
        start = int(time.time() * 1000)
        await self.wait_until(
            lambda: self.bot_said_something(since_ms=start),
            timeout=timeout,
            label="bot-say",
        )
        return start

    async def auto_answer_until(
        self,
        *,
        condition: Callable[[], bool],
        condition_label: str,
        fallback_reply: str = "由你全权决定，所有合理默认值都批准同意，请按 SOP 立即推进。",
        max_rounds: int = 8,
        timeout: float | None = None,
        reply_gap: float = 8.0,
    ) -> None:
        """反复回复 Bot 的澄清问题直到 condition() 返回 True。

        典型用法：
            await driver.auto_answer_until(
                condition=lambda: driver.has_event("project_created"),
                condition_label="project_created",
                timeout=900,
            )
        """
        timeout = timeout or self.options.long_wait
        deadline = time.time() + timeout
        rounds = 0
        last_bot_count = len(self.sender.messages)
        while time.time() < deadline:
            if condition():
                print(f"[AUTO_ANSWER] ✅ condition {condition_label!r} met after {rounds} reply rounds")
                return
            # wait for bot to respond to us (new message from bot after we last spoke)
            try:
                await self.wait_until(
                    lambda: len(self.sender.messages) > last_bot_count,
                    timeout=min(300, deadline - time.time()),
                    label=f"bot-reply-r{rounds}",
                )
            except TimeoutError:
                print(f"[AUTO_ANSWER] ⚠️  no bot reply in round {rounds}; retrying")
            if condition():
                print(f"[AUTO_ANSWER] ✅ condition {condition_label!r} met mid-round")
                return
            rounds += 1
            if rounds > max_rounds:
                raise TimeoutError(f"auto_answer exceeded max_rounds={max_rounds} without {condition_label}")
            last_bot_count = len(self.sender.messages)
            await asyncio.sleep(reply_gap)
            if condition():
                return
            print(f"[AUTO_ANSWER] round {rounds}: replying to push past clarification")
            await self.say(fallback_reply)
        raise TimeoutError(
            f"auto_answer_until({condition_label}) 超时 {timeout}s after {rounds} rounds"
        )

    # ── 调试 / 快照 ────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        pid = self.current_project_id()
        return {
            "project_id": pid,
            "files": self._list_files(self.proj_dir(pid)) if pid else {},
            "events_count": len(self.events(pid)),
            "event_actions": [e["action"] for e in self.events(pid)],
            "bot_msgs": len(self.sender.messages),
        }

    @staticmethod
    def _list_files(root: Path | None) -> dict:
        if root is None or not root.exists():
            return {}
        out: dict[str, int] = {}
        for p in root.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(root))
                out[rel] = p.stat().st_size
        return out


# ── pytest 装饰器：环境门槛 + 通用 fixture ────────────────────────────────


# pytest conftest 提供的公共 fixture
@pytest.fixture
async def driver(tmp_path: Path):
    """Full-journey E2E fixture：环境检查 → 创建 Driver、start、yield、stop（自动还原 workspace）."""
    require_env()  # 缺 QWEN_API_KEY 或沙盒不通 → pytest.skip
    backup = tmp_path / "workspace_backup"
    data = tmp_path / "data"
    drv = E2EDriver(backup_dir=backup, data_dir=data)
    await drv.start()
    try:
        yield drv
    finally:
        print("\n[DRIVER.stop] 清理 + 还原 workspace")
        snap = drv.snapshot()
        print(f"[SNAPSHOT] {json.dumps(snap, ensure_ascii=False, indent=2)[:800]}")
        await drv.stop()
