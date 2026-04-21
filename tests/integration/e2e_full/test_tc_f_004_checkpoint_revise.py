"""
TC-F-004 `with_checkpoint_revise` — 用户对需求 checkpoint 回 revise
"""
from __future__ import annotations

import pytest



@pytest.mark.e2e_full
async def test_tc_f_004_checkpoint_revise(driver) -> None:
    await driver.say(
        "帮我做个待办清单小网站（增/查/完成/删）。"
        "技术栈 FastAPI + SQLite + 原生 HTML/JS。"
        "**所有细节你直接替我决定，我批准任何合理方案**，请立即 create_project 并起草需求文档。"
    )

    await driver.auto_answer_until(
        condition=lambda: driver.has_event("project_created"),
        condition_label="project_created",
        timeout=1500, max_rounds=5,
    )
    await driver.wait_for_file("needs/requirements.md", timeout=600)
    # 等 Manager 发 checkpoint_request 给用户（bot_asked_for_checkpoint 检查最后一条消息是否含"同意/批准/确认"）
    await driver.wait_until(driver.bot_asked_for_checkpoint, timeout=600, label="needs-ckpt-1")

    # 用户 revise：加分享功能
    await driver.say("不对，MVP 还要加一个'分享当前任务列表到微信'的按钮。其他都同意。")

    # Manager 应再次产出需求草稿 + 再发 checkpoint
    await driver.wait_until(
        lambda: "分享" in driver.read_file("needs/requirements.md")
        or "微信" in driver.read_file("needs/requirements.md"),
        timeout=600,
        label="requirements.md 含分享",
    )
    # 应至少发过 2 次 send_to_human（第一次 ckpt + 第二次 ckpt）
    await driver.wait_until(
        lambda: driver.count_event("checkpoint_request_sent") >= 2,
        timeout=300,
        label="checkpoint_request_sent >= 2",
    )

    # 第二次 approve
    await driver.say("同意")

    # 往下推进
    await driver.wait_for_file("design/product_spec.md", timeout=900)
    spec = driver.read_file("design/product_spec.md")
    assert "分享" in spec or "微信" in spec, f"product_spec 未覆盖分享功能: {spec[:400]}"

    await driver.wait_for_file("tech/tech_design.md", timeout=900)
    await driver.wait_for_file("code/main.py", timeout=1200)
    await driver.wait_for_file("qa/test_plan.md", timeout=900)
    await driver.wait_for_file("qa/test_report.md", timeout=900)
    await driver.wait_for_event("delivery_sent", timeout=300)
    await driver.say("同意")
    await driver.wait_for_event("delivered", timeout=180)
