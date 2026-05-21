"""Tests for RedisMessageBus using fakeredis (no real Redis needed)."""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis as fakeredis_async
import pytest

from deeptutor.tutorbot.bus.events import InboundMessage, OutboundMessage


def _make_bus(bot_id: str = "testbot"):
    """Create a RedisMessageBus backed by a fresh in-memory FakeRedis."""
    import fakeredis
    from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus

    server = fakeredis.FakeServer()
    client = fakeredis_async.FakeRedis(server=server, decode_responses=True)
    return RedisMessageBus(bot_id=bot_id, redis_url="redis://localhost", _redis=client)


def _make_inbound(**kwargs) -> InboundMessage:
    defaults = dict(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    defaults.update(kwargs)
    return InboundMessage(**defaults)


@pytest.mark.asyncio
async def test_publish_and_consume():
    bus = _make_bus()
    msg = _make_inbound()
    await bus.publish_inbound(msg)
    result = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert result.content == "hello"
    assert result.channel == "telegram"


@pytest.mark.asyncio
async def test_consume_blocks_until_publish():
    bus = _make_bus()

    async def delayed_publish():
        await asyncio.sleep(0.05)
        await bus.publish_inbound(_make_inbound(content="delayed"))

    asyncio.create_task(delayed_publish())
    result = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert result.content == "delayed"


@pytest.mark.asyncio
async def test_stream_id_stored_in_metadata():
    bus = _make_bus()
    await bus.publish_inbound(_make_inbound())
    result = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert "_bus_stream_id" in result.metadata
    assert isinstance(result.metadata["_bus_stream_id"], str)


@pytest.mark.asyncio
async def test_ack_inbound():
    import fakeredis
    from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus

    server = fakeredis.FakeServer()
    client = fakeredis_async.FakeRedis(server=server, decode_responses=True)
    bus = RedisMessageBus(bot_id="testbot", redis_url="redis://localhost", _redis=client)

    await bus.publish_inbound(_make_inbound())
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)

    # Check PEL (pending entry list) has 1 entry before ack
    pel = await client.xpending("bot:testbot:inbound", "cg:testbot")
    assert pel["pending"] == 1

    await bus.ack_inbound(msg)

    pel_after = await client.xpending("bot:testbot:inbound", "cg:testbot")
    assert pel_after["pending"] == 0


@pytest.mark.asyncio
async def test_ack_noop_without_stream_id():
    bus = _make_bus()
    msg = _make_inbound()
    # msg has no _bus_stream_id in metadata — ack should be a no-op
    await bus.ack_inbound(msg)  # must not raise


@pytest.mark.asyncio
async def test_replay_pending_reclaims():
    """XAUTOCLAIM should reclaim unacked messages back to this consumer."""
    import fakeredis
    from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus

    server = fakeredis.FakeServer()

    # Bus A consumes but does NOT ack
    client_a = fakeredis_async.FakeRedis(server=server, decode_responses=True)
    bus_a = RedisMessageBus(bot_id="testbot", redis_url="redis://localhost", _redis=client_a)
    await bus_a.publish_inbound(_make_inbound(content="unacked"))
    await asyncio.wait_for(bus_a.consume_inbound(), timeout=2)
    # Do NOT ack

    # Bus B uses same server (same streams), simulating a restarted worker
    client_b = fakeredis_async.FakeRedis(server=server, decode_responses=True)
    bus_b = RedisMessageBus(bot_id="testbot", redis_url="redis://localhost", _redis=client_b)

    # replay_pending with min_idle_time=0 to force reclaim immediately in tests
    await bus_b.replay_pending(min_idle_time_ms=0)

    result = await asyncio.wait_for(bus_b.consume_inbound(), timeout=2)
    assert result.content == "unacked"


@pytest.mark.asyncio
async def test_replay_empty_is_safe():
    bus = _make_bus()
    await bus.replay_pending()  # empty stream — must not raise


@pytest.mark.asyncio
async def test_preserves_media_and_metadata():
    bus = _make_bus()
    msg = _make_inbound(
        media=["http://example.com/img.png"],
        metadata={"key": "val"},
    )
    await bus.publish_inbound(msg)
    result = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert result.media == ["http://example.com/img.png"]
    assert result.metadata["key"] == "val"


@pytest.mark.asyncio
async def test_preserves_session_key_override():
    bus = _make_bus()
    msg = _make_inbound(session_key_override="custom:session")
    await bus.publish_inbound(msg)
    result = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert result.session_key_override == "custom:session"


@pytest.mark.asyncio
async def test_preserves_attachments():
    bus = _make_bus()
    att = [{"type": "image", "base64": "abc", "mime_type": "image/png", "filename": "f.png"}]
    msg = _make_inbound(attachments=att)
    await bus.publish_inbound(msg)
    result = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert result.attachments == att


@pytest.mark.asyncio
async def test_outbound_passthrough():
    import fakeredis
    from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus

    server = fakeredis.FakeServer()
    # Worker bus publishes outbound
    worker_client = fakeredis_async.FakeRedis(server=server, decode_responses=True)
    worker_bus = RedisMessageBus(
        bot_id="testbot", redis_url="redis://localhost", _redis=worker_client
    )
    # Main-process bus consumes outbound (start from "0-0" to read all messages)
    main_client = fakeredis_async.FakeRedis(server=server, decode_responses=True)
    main_bus = RedisMessageBus(
        bot_id="testbot",
        redis_url="redis://localhost",
        _redis=main_client,
        _initial_outbound_id="0-0",
    )

    out = OutboundMessage(channel="telegram", chat_id="c1", content="response")
    await worker_bus.publish_outbound(out)

    result = await asyncio.wait_for(main_bus.consume_outbound(), timeout=2)
    assert result.content == "response"
    assert result.channel == "telegram"
