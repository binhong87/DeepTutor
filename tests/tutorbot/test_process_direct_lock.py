"""Regression: process_direct must acquire _processing_lock."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_process_direct_holds_processing_lock():
    """_processing_lock must be locked while _process_message runs from process_direct."""
    lock_states: list[bool] = []
    lock = asyncio.Lock()

    async def spy_process_message(self_inner, msg, **kwargs):
        lock_states.append(lock.locked())
        return None

    with (
        patch("deeptutor.tutorbot.agent.loop.AgentLoop._process_message", spy_process_message),
        patch("deeptutor.tutorbot.agent.loop.AgentLoop._connect_mcp", new_callable=AsyncMock),
    ):
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.queue import MessageBus

        with patch.object(AgentLoop, "__init__", lambda self, **kw: None):
            loop_obj = AgentLoop()

        loop_obj._processing_lock = lock
        loop_obj.bus = MessageBus()
        loop_obj.tools = {}
        loop_obj._default_session_key = "test:session"

        await loop_obj.process_direct("hello")

    assert lock_states == [True], (
        "process_direct must acquire _processing_lock before calling _process_message"
    )


@pytest.mark.asyncio
async def test_process_direct_and_dispatch_serialized():
    """A concurrent _dispatch call must wait for process_direct to finish."""
    execution_order: list[str] = []
    lock = asyncio.Lock()

    async def slow_process_message(self_inner, msg, **kwargs):
        execution_order.append(f"start:{msg.content}")
        if msg.content == "direct":
            await asyncio.sleep(0.05)
        execution_order.append(f"end:{msg.content}")
        return None

    with (
        patch("deeptutor.tutorbot.agent.loop.AgentLoop._process_message", slow_process_message),
        patch("deeptutor.tutorbot.agent.loop.AgentLoop._connect_mcp", new_callable=AsyncMock),
    ):
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.events import InboundMessage
        from deeptutor.tutorbot.bus.queue import MessageBus

        with patch.object(AgentLoop, "__init__", lambda self, **kw: None):
            loop_obj = AgentLoop()

        loop_obj._processing_lock = lock
        loop_obj.bus = MessageBus()
        loop_obj.tools = {}
        loop_obj._default_session_key = "test:session"

        channel_msg = InboundMessage(
            channel="telegram", sender_id="u", chat_id="c", content="channel"
        )

        await asyncio.gather(
            loop_obj.process_direct("direct"),
            loop_obj._dispatch(channel_msg),
        )

    assert execution_order.index("end:direct") < execution_order.index("start:channel")
