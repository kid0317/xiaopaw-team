"""
TC-F-007 `with_sop_cocreate_first` — 先共创 SOP 再跑功能开发

流程：3-4 轮 SOP 共创对话 → 生成草稿 → 用户 approve → 立即发需求开始跑 6 阶段.
"""
from __future__ import annotations

import pytest



@pytest.mark.e2e_full
async def test_tc_f_007_sop_cocreate_then_feature(driver) -> None:
    # ─── 阶段 A：SOP 共创 ────────────────────────────────────────────
    await driver.say("我们来定一套 '小功能开发' SOP 吧，帮我梳理完整流程。")
    await driver.wait_until(driver.bot_said_something, timeout=300, label="sop Q1")

    await driver.say(
        "Goal：快速把一个新功能从想法推到上线；"
        "Stages：需求澄清 → 产品设计 → RD 设计+实现 → QA 测试 → 交付 → 复盘；"
    )
    await driver.wait_until(
        lambda: len(driver.sender.messages) >= 2, timeout=300, label="sop Q2"
    )

    await driver.say(
        "Roles：Manager 总负责；PM 产品设计；RD 技术实现；QA 测试；"
        "Artifacts：每阶段在 shared/projects/{pid} 下对应目录产出；"
    )
    await driver.wait_until(
        lambda: len(driver.sender.messages) >= 3, timeout=300, label="sop Q3"
    )

    await driver.say(
        "Checkpoints：需求定稿 + 交付验收 两个；"
        "Retrospective：每次交付后 24h 自动复盘。"
    )
    # 等 Manager 发 SOP 草稿的 checkpoint
    await driver.wait_until(
        driver.bot_asked_for_checkpoint, timeout=600, label="sop-checkpoint"
    )
    await driver.say("同意，就按这个 SOP")

    # ─── 阶段 B：按新 SOP 跑一个项目 ────────────────────────────────
    await driver.say(
        "好，现在请按刚才定的 SOP 帮我做个待办清单小网站（增/查/完成/删）。"
        "栈 FastAPI+SQLite+HTML/JS。一次只问一个问题，否则直接推进。"
    )

    await driver.wait_for_event("project_created", timeout=600)
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
