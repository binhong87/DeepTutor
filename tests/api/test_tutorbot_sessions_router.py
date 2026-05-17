"""Tests for the new per-session TutorBot endpoints."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


def _mount(monkeypatch, fake_manager):
    """Stand up a FastAPI app with the tutorbot router and a fake manager."""
    import deeptutor.api.routers.tutorbot as router_mod

    monkeypatch.setattr(router_mod, "get_tutorbot_manager", lambda: fake_manager)
    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api/v1/tutorbot")
    return TestClient(app)


def _running_instance():
    return SimpleNamespace(
        running=True,
        notify_queue=asyncio.Queue(),
        agent_loop=SimpleNamespace(sessions=None),
    )


def test_session_promoted_event_pushed_on_plan_lesson(monkeypatch):
    """When send_message triggers plan_lesson, the WS client receives session_promoted."""
    promoted_payload = {
        "promoted": {
            "id": "s_default",
            "title": "Lesson Title",
            "title_source": "lesson_plan",
            "lesson_plan_brief": None,
        },
        "new_default": {"id": "s_abc", "title": "", "status": "default"},
    }

    class FakeMgr:
        def get_bot(self, _bid):
            return _running_instance()

        def load_bot_config(self, _bid):
            return SimpleNamespace(
                name="b", channels={}, model=None, llm_selection=None,
                description="", persona="",
            )

        async def start_bot(self, *_a, **_kw):
            return _running_instance()

        async def send_message(
            self, _bid, _content, *, chat_id, session_id,
            on_progress=None, on_lesson_update=None, on_session_promoted=None,
        ):
            assert session_id == "s_default"
            if on_session_promoted:
                await on_session_promoted(promoted_payload["promoted"],
                                          promoted_payload["new_default"])
            return "reply"

    client = _mount(monkeypatch, FakeMgr())
    with client.websocket_connect("/api/v1/tutorbot/b/sessions/s_default/ws") as ws:
        ws.send_text(json.dumps({"content": "hi"}))
        types_seen = []
        for _ in range(6):
            msg = ws.receive_json()
            types_seen.append(msg["type"])
            if msg["type"] == "session_promoted":
                assert msg["promoted"]["title"] == "Lesson Title"
                assert msg["new_default"]["status"] == "default"
            if msg["type"] == "done":
                break
        assert "session_promoted" in types_seen
        assert "content" in types_seen


def test_list_sessions_returns_default_first(monkeypatch):
    class FakeMgr:
        def list_sessions(self, _bid):
            return [
                {"id": "s_default", "title": "", "title_source": None,
                 "status": "default", "updated_at": "2026-05-17T10:00:00",
                 "has_user_messages": False, "lesson_plan_brief": None},
                {"id": "s_a", "title": "Lesson A", "title_source": "lesson_plan",
                 "status": "active", "updated_at": "2026-05-17T09:00:00",
                 "has_user_messages": True,
                 "lesson_plan_brief": {"topic": "Lesson A", "current_step_id": "s1",
                                       "total_steps": 3, "done_steps": 1}},
            ]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/b1/sessions")
    assert res.status_code == 200
    rows = res.json()
    assert rows[0]["status"] == "default"
    assert rows[1]["title"] == "Lesson A"
    assert rows[1]["lesson_plan_brief"]["done_steps"] == 1


def test_post_sessions_409_when_default_empty(monkeypatch):
    class FakeMgr:
        def create_session(self, _bid):
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail={"existing_default_id": "s_default"})
    client = _mount(monkeypatch, FakeMgr())
    res = client.post("/api/v1/tutorbot/b1/sessions")
    assert res.status_code == 409
    assert res.json()["detail"]["existing_default_id"] == "s_default"


def test_post_sessions_201_when_default_non_empty(monkeypatch):
    class FakeMgr:
        def create_session(self, _bid):
            return {"id": "s_new", "title": "", "title_source": None,
                    "status": "default", "updated_at": "2026-05-17T10:01:00",
                    "has_user_messages": False, "lesson_plan_brief": None}
    client = _mount(monkeypatch, FakeMgr())
    res = client.post("/api/v1/tutorbot/b1/sessions")
    assert res.status_code == 201
    assert res.json()["id"] == "s_new"
    assert res.json()["status"] == "default"


def test_get_session_history(monkeypatch):
    class FakeMgr:
        def get_bot_history(self, _bid, *, session_id, limit=100):
            assert session_id == "s_abc"
            return [{"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"}]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/b1/sessions/s_abc/history")
    assert res.status_code == 200
    assert [m["role"] for m in res.json()] == ["user", "assistant"]


def test_tree_returns_all_bots_with_sessions(monkeypatch):
    class FakeMgr:
        def get_tree(self):
            return [
                {"bot_id": "b1", "name": "Math", "running": True, "sessions": [
                    {"id": "s_default", "title": "", "title_source": None,
                     "status": "default", "updated_at": "2026-05-17",
                     "has_user_messages": False, "lesson_plan_brief": None},
                ]},
                {"bot_id": "b2", "name": "Chem", "running": False, "sessions": []},
            ]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/tree")
    assert res.status_code == 200
    tree = res.json()
    assert len(tree) == 2
    assert tree[0]["sessions"][0]["status"] == "default"


def test_legacy_history_still_works(monkeypatch):
    """GET /tutorbot/{bot_id}/history should resolve to the default session."""
    class FakeMgr:
        def get_bot_history(self, _bid, *, session_id=None, limit=100):
            assert session_id is None
            return [{"role": "user", "content": "from default"}]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/b1/history")
    assert res.status_code == 200
    assert res.json()[0]["content"] == "from default"
