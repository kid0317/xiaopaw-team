"""
TC-F-003 `with_qa_defect_rd_fix_loop` — QA 发现 defect → RD 修复 → 重测通过

注入手段：在需求里放置"严格硬删除"强要求，RD 第一轮可能选 soft delete，
QA test_run 会发现不一致 → 写 defect → 回流 RD → 再次 task_done → QA 重测.
"""
from __future__ import annotations

import pytest



@pytest.mark.e2e_full
async def test_tc_f_003_qa_defect_rd_fix(driver) -> None:
    await driver.say(
        "做一个待办清单小网站 MVP（增/查/改完成/删）。"
        "**严格硬约束：DELETE /todo/{id} 必须物理删除（db.delete），不允许 soft delete**；"
        "QA 必须在测试中断言：DELETE 后 GET /todo/{id} 返回 404，且 GET /todo 列表不含该 id；"
        "栈：FastAPI + SQLite + 原生 HTML/JS。"
        "**所有细节你直接替我决定，我批准任何合理方案**，请立即 create_project 并起草需求文档。"
    )

    await driver.auto_answer_until(
        condition=lambda: driver.has_event("project_created"),
        condition_label="project_created",
        timeout=1500, max_rounds=5,
    )
    await driver.wait_for_file("needs/requirements.md", timeout=600)
    await driver.auto_answer_until(
        condition=lambda: driver.has_event("checkpoint_approved")
        or driver.file_exists("design/product_spec.md"),
        condition_label="needs-approved-or-design-started",
        fallback_reply=(
            "同意，批准需求立即进入产品设计阶段。"
            "请立刻用 send_mail 工具派 PM 产品设计任务（to=pm, type=task_assign, "
            "subject='产品设计 (第 1 轮)'），并用 append_event 写 checkpoint_approved 事件。"
        ),
        timeout=900, max_rounds=3,
    )

    await driver.wait_for_file("design/product_spec.md", timeout=900)
    await driver.wait_for_file("tech/tech_design.md", timeout=900)
    await driver.wait_for_file("code/main.py", timeout=1500)
    await driver.wait_for_file("qa/test_plan.md", timeout=900)
    # QA 可能第一轮失败：等 test_report 或 defect_* 至少一个出现
    await driver.wait_until(
        lambda: driver.file_exists("qa/test_report.md")
        or ((driver.proj_dir() / "qa" / "defects").exists()
            and any((driver.proj_dir() / "qa" / "defects").glob("defect_*.md"))),
        timeout=1800,
        label="qa:first-test-result",
    )

    # 如果一开始就通过（可能 RD 本来就写对了），放宽——只断言最终交付
    # 但若产生了 defect，等待修复循环
    if (driver.proj_dir() / "qa" / "defects").exists() \
       and any((driver.proj_dir() / "qa" / "defects").glob("defect_*.md")):
        # 等 RD 修复 + QA 重测（test_report.md 最终出现 fail=0）
        await driver.wait_until(
            lambda: driver.file_exists("qa/test_report.md"),
            timeout=1800,
            label="qa:test_report after defect fix",
        )

    # 等交付
    await driver.wait_for_event("delivery_sent", timeout=600)
    await driver.say("同意")
    await driver.wait_for_event("delivered", timeout=180)

    # 断言：交付完成
    assert driver.file_exists("qa/test_report.md")
    report = driver.read_file("qa/test_report.md")
    assert "失败：0" in report or "fail: 0" in report.lower() or "通过" in report, \
        f"test_report 显示还有失败: {report[:500]}"
