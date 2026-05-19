"""Integration test: verify send_message forwards attachments to ContextBuilder.

T9b — attachments plumbing from WS JSON through manager.send_message to
ContextBuilder.build_user_message_with_media.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deeptutor.services.tutorbot.manager import BotConfig, TutorBotInstance, TutorBotManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> TutorBotManager:
    from deeptutor.multi_user.models import UserScope

    scope = UserScope(
        kind="user",
        user_id="test-user",
        root=(tmp_path / "test-user").resolve(),
    )
    return TutorBotManager(scope=scope)


def _make_fake_agent_loop(captured: dict) -> MagicMock:
    """Return a fake AgentLoop whose process_direct records call kwargs."""
    loop = MagicMock()
    loop.sessions = MagicMock()
    loop.sessions.ensure_default_session.return_value = SimpleNamespace(
        key="bot:test-bot:s:default"
    )
    loop.set_session_promoted_callback = MagicMock()

    async def fake_process_direct(content, *, attachments=None, **kwargs):
        captured["content"] = content
        captured["attachments"] = attachments
        captured["kwargs"] = kwargs
        return "ok"

    loop.process_direct = fake_process_direct
    return loop


def _register_running_bot(
    manager: TutorBotManager, bot_id: str, agent_loop
) -> TutorBotInstance:
    """Register a fake running bot. `running` is a property derived from tasks."""
    cfg = BotConfig(name=bot_id)
    instance = TutorBotInstance(bot_id=bot_id, config=cfg)
    # Make the instance appear "running" by adding a never-done task.
    dummy_task = asyncio.get_event_loop().create_future()
    instance.tasks = [dummy_task]  # type: ignore[assignment]
    instance.agent_loop = agent_loop
    instance.channel_manager = None
    instance.notify_queue = asyncio.Queue()
    manager._bots[bot_id] = instance
    return instance


# ---------------------------------------------------------------------------
# Tests: send_message → process_direct attachment forwarding
# ---------------------------------------------------------------------------


class TestSendMessageAttachmentsPropagation:
    """Verify attachments flow from send_message → process_direct."""

    def test_send_message_with_no_attachments_passes_none(self, tmp_path: Path) -> None:
        """Baseline: None attachments are forwarded as None (not [])."""
        manager = _make_manager(tmp_path)
        captured: dict = {}

        async def run():
            loop = asyncio.get_event_loop()
            agent_loop = _make_fake_agent_loop(captured)
            _register_running_bot(manager, "bot-a", agent_loop)
            return await manager.send_message("bot-a", "hello")

        asyncio.run(run())

        assert captured["content"] == "hello"
        assert captured["attachments"] is None

    def test_send_message_forwards_attachment_list(self, tmp_path: Path) -> None:
        """Attachments passed to send_message reach process_direct unchanged."""
        manager = _make_manager(tmp_path)
        captured: dict = {}

        wire_attachments = [
            {"type": "image", "base64": "abc==", "mime_type": "image/png", "filename": "x.png"}
        ]

        async def run():
            agent_loop = _make_fake_agent_loop(captured)
            _register_running_bot(manager, "bot-b", agent_loop)
            return await manager.send_message(
                "bot-b", "what is this?", attachments=wire_attachments
            )

        asyncio.run(run())

        assert captured["content"] == "what is this?"
        assert captured["attachments"] == wire_attachments

    def test_send_message_multiple_attachments(self, tmp_path: Path) -> None:
        """Multiple attachments are forwarded as a list."""
        manager = _make_manager(tmp_path)
        captured: dict = {}

        wire_attachments = [
            {"type": "image", "base64": "abc==", "mime_type": "image/png", "filename": "a.png"},
            {"type": "audio", "base64": "def==", "mime_type": "audio/webm", "filename": "b.webm"},
        ]

        async def run():
            agent_loop = _make_fake_agent_loop(captured)
            _register_running_bot(manager, "bot-c", agent_loop)
            return await manager.send_message(
                "bot-c", "describe both", attachments=wire_attachments
            )

        asyncio.run(run())

        assert captured["attachments"] == wire_attachments
        assert len(captured["attachments"]) == 2


# ---------------------------------------------------------------------------
# Tests: process_direct → build_user_message_with_media in the real loop
# ---------------------------------------------------------------------------


class TestProcessDirectAttachmentsReachContextBuilder:
    """Verify process_direct → _process_message calls build_user_message_with_media."""

    def _make_loop(self, tmp_path: Path):
        """Build a real AgentLoop with a fake provider."""
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.queue import MessageBus

        fake_provider = MagicMock()
        fake_provider.get_default_model.return_value = "gpt-4o"
        fake_provider.generation = SimpleNamespace(
            temperature=0.7, max_tokens=4096, reasoning_effort=None
        )
        # binding property needed for build_user_message_with_media
        type(fake_provider).binding = "openai"

        bus = MessageBus()
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)

        agent_loop = AgentLoop(
            bus=bus,
            provider=fake_provider,
            workspace=workspace,
            model="gpt-4o",
        )
        return agent_loop

    def test_build_user_message_with_media_called_when_attachments_present(
        self, tmp_path: Path
    ) -> None:
        """When process_direct is called with wire-dict attachments,
        build_user_message_with_media is invoked on the ContextBuilder."""
        loop = self._make_loop(tmp_path)

        wire_attachments = [
            {
                "type": "image",
                "base64": "abc==",
                "mime_type": "image/png",
                "filename": "x.png",
            }
        ]

        call_args: dict = {}

        def fake_build(text, attachments, *, binding, model):
            call_args["text"] = text
            call_args["attachments"] = attachments
            call_args["binding"] = binding
            call_args["model"] = model
            return text  # return plain text to keep pipeline simple

        async def fake_run_agent_loop(messages, **kwargs):
            return ("stub reply", None, messages, False)

        loop.context.build_user_message_with_media = fake_build
        loop._run_agent_loop = fake_run_agent_loop  # type: ignore[assignment]

        async def run():
            return await loop.process_direct(
                "what is this?",
                attachments=wire_attachments,
                session_key="web:direct",
            )

        asyncio.run(run())

        assert call_args, "build_user_message_with_media was never called"
        assert call_args["binding"] == "openai"
        assert len(call_args["attachments"]) == 1
        att = call_args["attachments"][0]
        # Must be converted to Attachment dataclass
        from deeptutor.core.context import Attachment

        assert isinstance(att, Attachment)
        assert att.type == "image"
        # Phase 2: persist_attachments runs before build_user_message_with_media,
        # persisting the base64 bytes to the AttachmentStore and clearing the
        # in-memory base64. After persistence, the attachment carries a url
        # ref instead of inline bytes.
        assert att.base64 == "", f"expected base64 cleared post-persist, got {att.base64!r}"
        assert att.url.startswith("/api/attachments/"), f"expected URL ref post-persist, got {att.url!r}"
        assert att.mime_type == "image/png"
        assert att.filename == "x.png"

    def test_plain_text_path_unchanged_when_no_attachments(self, tmp_path: Path) -> None:
        """When no attachments, build_messages is used (not build_user_message_with_media)."""
        loop = self._make_loop(tmp_path)

        media_build_calls: list = []
        original_with_media = loop.context.build_user_message_with_media

        def fake_with_media(*args, **kwargs):
            media_build_calls.append((args, kwargs))
            return original_with_media(*args, **kwargs)

        loop.context.build_user_message_with_media = fake_with_media

        async def fake_run_agent_loop(messages, **kwargs):
            return ("plain reply", None, messages, False)

        loop._run_agent_loop = fake_run_agent_loop  # type: ignore[assignment]

        async def run():
            return await loop.process_direct("hello")

        asyncio.run(run())

        assert media_build_calls == [], (
            "build_user_message_with_media must NOT be called without attachments"
        )
