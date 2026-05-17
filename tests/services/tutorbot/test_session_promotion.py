"""Tests for SessionManager.promote_default."""

from __future__ import annotations

from deeptutor.tutorbot.session.manager import SessionManager


def _seed_default_with_msg(tmp_path, bot_id="b1"):
    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session(bot_id)
    default.add_message("user", "what is x?")
    mgr.save(default)
    return mgr, default


def test_promote_default_renames_default_and_allocates_new(tmp_path):
    mgr, default = _seed_default_with_msg(tmp_path)
    promoted, new_default = mgr.promote_default(
        default, title="二元一次方程的解法", title_source="lesson_plan", completed=False,
    )

    assert promoted.key == default.key
    assert promoted.metadata["title"] == "二元一次方程的解法"
    assert promoted.metadata["title_source"] == "lesson_plan"
    assert promoted.metadata["status"] == "active"

    assert new_default is not None
    assert new_default.metadata["status"] == "default"
    assert new_default.key != promoted.key

    rows = mgr.list_for_bot("b1")
    keys = {r["key"] for r in rows}
    assert promoted.key in keys
    assert new_default.key in keys
    assert sum(1 for r in rows if r["status"] == "default") == 1


def test_promote_default_with_completed_sets_status(tmp_path):
    mgr, default = _seed_default_with_msg(tmp_path)
    promoted, _ = mgr.promote_default(
        default, title="", title_source="manual", completed=True,
    )
    assert promoted.metadata["status"] == "completed"


def test_promote_default_noop_when_already_promoted(tmp_path):
    mgr, default = _seed_default_with_msg(tmp_path)
    mgr.promote_default(default, title="Lesson A", title_source="lesson_plan", completed=False)
    promoted, new_default = mgr.promote_default(
        default, title="Lesson B", title_source="lesson_plan", completed=False,
    )
    assert promoted is default
    assert new_default is None
    assert promoted.metadata["title"] == "Lesson A"
