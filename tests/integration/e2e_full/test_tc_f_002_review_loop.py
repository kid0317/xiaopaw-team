"""
TC-F-002 `with_low_self_score_review_loop` — 插评审 + revise 全链路.

场景：在需求里注入"高风险"暗示（用户明确要求"涉及付费/涉及登录/高并发"）以触发
impact_level=high → Manager check_review_criteria threshold_met=true → 走评审插入流程.
"""
from __future__ import annotations

import pytest



@pytest.mark.e2e_full
async def test_tc_f_002_review_loop(driver) -> None:
    await driver.say(
        "帮我做个待办清单小网站，**包含用户登录、付费订阅**两大 MVP 功能。"
        "因为涉及账号和付款，质量要求很高，**请你在每个阶段都主动插入团队评审**。"
        "技术栈 FastAPI + SQLite + 原生 HTML+JS。"
        "一次只问一个关键问题；否则直接推进。"
    )

    await driver.wait_for_event("project_created", timeout=300)
    pid = driver.current_project_id()

    # 等需求 + 用户 approve
    await driver.wait_for_file("needs/requirements.md", timeout=600)
    await driver.wait_until(driver.bot_asked_for_checkpoint, timeout=300, label="needs-ckpt")
    await driver.say("同意")

    # 等产品设计 + 至少发出一次 review_request
    await driver.wait_for_file("design/product_spec.md", timeout=900)
    await driver.wait_for_event("review_requested", timeout=600)
    # 至少有 1 条 reviews/product_design/*.md
    await driver.wait_until(
        lambda: (driver.proj_dir() / "reviews" / "product_design").exists()
        and any((driver.proj_dir() / "reviews" / "product_design").glob("*.md")),
        timeout=900,
        label="reviews/product_design/*.md",
    )

    # 继续推进到交付
    await driver.wait_for_file("tech/tech_design.md", timeout=900)
    await driver.wait_for_file("code/main.py", timeout=1200)
    await driver.wait_for_file("qa/test_plan.md", timeout=900)
    await driver.wait_for_file("qa/test_report.md", timeout=900)

    await driver.wait_for_event("delivery_sent", timeout=300)
    await driver.say("同意")
    await driver.wait_for_event("delivered", timeout=180)

    # 断言
    assert driver.has_event("review_requested")
    assert driver.has_event("review_received")
    assert driver.count_event("review_requested") >= 1
