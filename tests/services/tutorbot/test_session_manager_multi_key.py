"""Tests for SessionManager multi-key (bot:<id>:s:<sid>) operations."""

from __future__ import annotations

import time

from deeptutor.tutorbot.session.ids import DEFAULT_SID, new_session_id
from deeptutor.tutorbot.session.manager import SessionManager


def test_default_sid_constant():
    assert DEFAULT_SID == "s_default"


def test_new_session_id_unique_and_prefixed():
    ids = {new_session_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(s.startswith("s_") for s in ids)
    assert all(s != DEFAULT_SID for s in ids)
    assert all(8 <= len(s) <= 32 for s in ids)


def _mk_session(mgr: SessionManager, key: str, status: str = "active", title: str = "", **meta) -> None:
    s = mgr.get_or_create(key)
    s.metadata.update({"status": status, "title": title, **meta})
    s.add_message("user", "hi")
    mgr.save(s)


def test_list_for_bot_returns_only_matching_bot(tmp_path):
    mgr = SessionManager(tmp_path)
    _mk_session(mgr, "bot:b1:s:s_default", status="default")
    _mk_session(mgr, "bot:b1:s:s_aaaa", status="active", title="Alpha")
    _mk_session(mgr, "bot:b2:s:s_bbbb", status="active", title="Beta")

    rows = mgr.list_for_bot("b1")
    keys = [r["key"] for r in rows]
    assert "bot:b1:s:s_default" in keys
    assert "bot:b1:s:s_aaaa" in keys
    assert "bot:b2:s:s_bbbb" not in keys


def test_list_for_bot_orders_default_first_then_updated_at_desc(tmp_path):
    mgr = SessionManager(tmp_path)
    _mk_session(mgr, "bot:b1:s:s_old", status="active", title="Old")
    time.sleep(0.01)
    _mk_session(mgr, "bot:b1:s:s_default", status="default")
    time.sleep(0.01)
    _mk_session(mgr, "bot:b1:s:s_new", status="active", title="New")

    rows = mgr.list_for_bot("b1")
    statuses = [r["status"] for r in rows]
    titles = [r["title"] for r in rows]

    assert statuses[0] == "default"
    assert titles[1] == "New"
    assert titles[2] == "Old"


def test_ensure_default_creates_with_bootstrap_id(tmp_path):
    mgr = SessionManager(tmp_path)
    session = mgr.ensure_default_session("b1")
    assert session.metadata["status"] == "default"
    assert session.key == "bot:b1:s:s_default"

    again = mgr.ensure_default_session("b1")
    assert again.key == session.key


def test_ensure_default_reuses_existing_default(tmp_path):
    mgr = SessionManager(tmp_path)
    s = mgr.get_or_create("bot:b1:s:s_freshdef")
    s.metadata.update({"status": "default", "title": ""})
    mgr.save(s)

    session = mgr.ensure_default_session("b1")
    assert session.key == "bot:b1:s:s_freshdef"
