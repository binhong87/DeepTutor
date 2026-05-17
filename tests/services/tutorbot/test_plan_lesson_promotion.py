"""Tests that PlanLessonTool promotes default sessions via SessionManager."""

from __future__ import annotations

import asyncio

from deeptutor.tutorbot.agent.tools.lesson import PlanLessonTool
from deeptutor.tutorbot.session.manager import SessionManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_plan_lesson_promotes_default_session(tmp_path):
    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session("b1")
    default.add_message("user", "teach me equations")
    mgr.save(default)

    promotions: list[tuple[str, str | None]] = []

    def on_promoted(promoted_key: str, new_default_key: str | None) -> None:
        promotions.append((promoted_key, new_default_key))

    tool = PlanLessonTool()
    tool.set_session_accessor(
        getter=lambda: default,
        on_update=None,
        session_manager=mgr,
        on_session_promoted=on_promoted,
    )

    result = _run(tool.execute(
        topic="二元一次方程的解法",
        steps=[{"id": "s1", "phase": "define", "goal": "Define linear equation"}],
    ))

    assert "Plan committed" in result
    assert default.metadata["status"] == "active"
    assert default.metadata["title"] == "二元一次方程的解法"
    assert len(promotions) == 1
    promoted_key, new_default_key = promotions[0]
    assert promoted_key == default.key
    assert new_default_key and new_default_key != default.key


def test_plan_lesson_in_active_session_updates_in_place(tmp_path):
    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session("b1")
    default.add_message("user", "x?")
    mgr.save(default)
    mgr.promote_default(default, title="Old topic", title_source="lesson_plan", completed=False)

    promotions: list = []
    tool = PlanLessonTool()
    tool.set_session_accessor(
        getter=lambda: default,
        on_update=None,
        session_manager=mgr,
        on_session_promoted=lambda *a: promotions.append(a),
    )

    _run(tool.execute(
        topic="New topic",
        steps=[{"id": "s1", "phase": "define", "goal": "redefine"}],
    ))

    assert default.metadata["title"] == "New topic"
    assert promotions == []
