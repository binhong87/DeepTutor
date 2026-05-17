"""Tests for G1 lazy migration of legacy per-bot JSONL."""

from __future__ import annotations

import json

from deeptutor.tutorbot.session.manager import SessionManager
from deeptutor.tutorbot.utils.helpers import safe_filename


def _write_legacy(tmp_path, bot_id: str, messages: list[dict], lesson_plan: dict | None = None) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    safe_bot = safe_filename(bot_id)
    path = sessions_dir / f"bot_{safe_bot}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        meta = {
            "_type": "metadata",
            "key": f"bot:{bot_id}",
            "created_at": "2026-04-01T00:00:00",
            "updated_at": "2026-04-01T01:00:00",
            "metadata": ({"lesson_plan": lesson_plan} if lesson_plan else {}),
            "last_consolidated": 0,
        }
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def test_migration_creates_archived_session_and_fresh_default(tmp_path):
    bot_id = "math-tutor"
    _write_legacy(tmp_path, bot_id, [
        {"role": "user", "content": "hi", "timestamp": "2026-04-01T00:00:00"},
        {"role": "assistant", "content": "hello", "timestamp": "2026-04-01T00:00:01"},
    ])

    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session(bot_id)

    rows = mgr.list_for_bot(bot_id)
    statuses = sorted(r["status"] for r in rows)
    titles = {r["status"]: r["title"] for r in rows}

    assert statuses == ["archived", "default"]
    assert titles["archived"] == "之前的对话"
    assert default.metadata["status"] == "default"

    safe_bot = safe_filename(bot_id)
    legacy = tmp_path / "sessions" / f"bot_{safe_bot}.jsonl"
    migrated = tmp_path / "sessions" / f"bot_{safe_bot}.jsonl.migrated"
    assert not legacy.exists()
    assert migrated.exists()


def test_migration_is_idempotent(tmp_path):
    bot_id = "b1"
    _write_legacy(tmp_path, bot_id, [{"role": "user", "content": "hi"}])

    mgr1 = SessionManager(tmp_path)
    mgr1.ensure_default_session(bot_id)
    rows_before = mgr1.list_for_bot(bot_id)

    mgr2 = SessionManager(tmp_path)
    mgr2.ensure_default_session(bot_id)
    rows_after = mgr2.list_for_bot(bot_id)

    assert len(rows_before) == len(rows_after) == 2


def test_migration_refuses_when_both_legacy_and_migrated_exist(tmp_path):
    bot_id = "b1"
    _write_legacy(tmp_path, bot_id, [{"role": "user", "content": "hi"}])
    safe_bot = safe_filename(bot_id)
    (tmp_path / "sessions" / f"bot_{safe_bot}.jsonl.migrated").write_text("{}\n", encoding="utf-8")

    mgr = SessionManager(tmp_path)
    mgr.ensure_default_session(bot_id)

    legacy = tmp_path / "sessions" / f"bot_{safe_bot}.jsonl"
    assert legacy.exists()
    rows = mgr.list_for_bot(bot_id)
    statuses = sorted(r["status"] for r in rows)
    assert "archived" not in statuses
