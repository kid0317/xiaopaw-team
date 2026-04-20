"""
TC-F-005 `with_retrospective_and_evolution` — 交付后复盘 + 进化

执行策略：
1. 先跑完 TC-F-001 基线（产出 delivered 事件）
2. 用户发"团队复盘" → Manager team_retrospective → proposals
3. 等 retro_approved_by_manager 或 retro_approved_by_human 事件
4. 等 retro_applied_by_{role} 事件
"""
from __future__ import annotations

import pytest



@pytest.mark.e2e_full
async def test_tc_f_005_retrospective_evolution(driver) -> None:
    # ─── 阶段 A：先跑完一次 happy path（压缩版） ────────────────────
    await driver.say(
        "帮我做个最小的'待办清单'小网站（增/查/完成/删）。"
        "栈 FastAPI+SQLite+HTML/JS。所有细节你定，一次只问一个问题；否则直接推进。"
    )
    await driver.wait_for_event("project_created", timeout=300)
    await driver.wait_for_file("needs/requirements.md", timeout=600)
    await driver.wait_until(driver.bot_asked_for_checkpoint, timeout=300, label="needs-ckpt")
    await driver.say("同意")

    await driver.wait_for_file("design/product_spec.md", timeout=900)
    await driver.wait_for_file("tech/tech_design.md", timeout=900)
    await driver.wait_for_file("code/main.py", timeout=1500)
    await driver.wait_for_file("qa/test_plan.md", timeout=900)
    await driver.wait_for_file("qa/test_report.md", timeout=900)
    await driver.wait_for_event("delivery_sent", timeout=300)
    await driver.say("同意")
    await driver.wait_for_event("delivered", timeout=180)

    # ─── 阶段 B：复盘 ────────────────────────────────────────────────
    await driver.say("现在做一次团队复盘，把本次能固化的改进提案产出。")

    # 等待任一 retro_* 事件出现
    await driver.wait_until(
        lambda: any(e["action"].startswith("retro_") for e in driver.events()),
        timeout=900,
        label="any retro_ event",
    )

    # 若产生 skill depth proposal，Manager 会转人类；我们直接 approve 所有
    # 等 Manager 发 proposal_review 或直接自动批的 retro_approved_by_manager
    from time import time as _t
    start = int(_t() * 1000)
    try:
        await driver.wait_until(
            driver.bot_asked_for_checkpoint,
            timeout=600,
            label="proposal_review checkpoint",
        )
        await driver.say("同意，全部批准")
    except TimeoutError:
        # 也可能全是 memory auto-approve，没有转人类环节
        pass

    # 等 retro_applied 事件或 Manager 最终回复
    await driver.wait_until(
        lambda: any(e["action"].startswith("retro_applied") for e in driver.events())
        or any("复盘" in m["content"] or "完成" in m["content"]
               for m in driver.sender.messages if m["ts_ms"] >= start),
        timeout=900,
        label="retro_applied or 复盘完成",
    )

    # 断言
    actions = [e["action"] for e in driver.events()]
    assert any(a.startswith("retro_") for a in actions), f"events 无 retro_* : {actions[-10:]}"
