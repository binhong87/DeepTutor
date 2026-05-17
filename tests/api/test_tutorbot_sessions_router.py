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
