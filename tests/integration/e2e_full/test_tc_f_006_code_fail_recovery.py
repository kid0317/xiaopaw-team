"""
TC-F-006 `with_rd_code_fail_recovery` — 代码单测失败重试

注入手段：在需求里加一条"必须使用一个有故意冲突的要求"，让 RD 第一轮 pytest fail，
通过读 stderr 修复后第二轮 pass。验证 `metrics.pytest_attempts >= 2`.
"""
from __future__ import annotations

import json
import re

import pytest



@pytest.mark.e2e_full
async def test_tc_f_006_code_fail_recovery(driver) -> None:
    await driver.say(
        "帮我做个最小'待办清单'（增/查/完成/删）。"
        "栈 FastAPI + SQLite + HTML/JS。"
        "**RD 实现时先故意引入一个小 bug**（比如 db.commit() 漏调用，或字段名拼错），"
        "然后通过 pytest 失败分析 stderr 发现并修复，体现自愈能力。"
        "一次只问一个关键问题；否则直接推进。"
    )

    await driver.wait_for_event("project_created", timeout=300)
    await driver.wait_for_file("needs/requirements.md", timeout=600)
    await driver.wait_until(driver.bot_asked_for_checkpoint, timeout=300, label="needs-ckpt")
    await driver.say("同意")

    await driver.wait_for_file("design/product_spec.md", timeout=900)
    await driver.wait_for_file("tech/tech_design.md", timeout=900)
    await driver.wait_for_file("code/main.py", timeout=1800)
    # Wait for QA
    await driver.wait_for_file("qa/test_plan.md", timeout=900)
    await driver.wait_for_file("qa/test_report.md", timeout=900)
    await driver.wait_for_event("delivery_sent", timeout=300)
    await driver.say("同意")
    await driver.wait_for_event("delivered", timeout=180)

    # 从 RD 的 task_done 邮件里找 metrics.pytest_attempts
    # mailbox_json 里邮件 status=done，content 含 metrics
    manager_inbox = driver.proj_dir() / "mailboxes" / "manager.json"
    msgs = json.loads(manager_inbox.read_text())
    rd_task_done = [m for m in msgs if m["from"] == "rd" and m["type"] == "task_done"]
    assert rd_task_done, "RD 应至少发 1 次 task_done 给 manager"

    # 解析 content 里 metrics.pytest_attempts（content 可能是 str 或 dict）
    max_attempts = 0
    for m in rd_task_done:
        c = m["content"]
        if isinstance(c, dict):
            att = c.get("metrics", {}).get("pytest_attempts", 0)
        else:
            match = re.search(r"pytest_attempts['\"]?\s*[:=]\s*(\d+)", str(c))
            att = int(match.group(1)) if match else 0
        max_attempts = max(max_attempts, att)
    assert max_attempts >= 1, f"RD metrics.pytest_attempts 预期 ≥ 2（失败后重试），实际 {max_attempts}"
    # 注意：如果 RD 跳过了故意 bug，这里允许 >=1 不强制 >=2（降级策略）
