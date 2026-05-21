"""Unit tests for SqliteMessageBus."""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from deeptutor.tutorbot.bus.events import InboundMessage, OutboundMessage


def _make_msg(content: str = "hello", channel: str = "web") -> InboundMessage:
    return InboundMessage(
        channel=channel,
        sender_id="u1",
        chat_id="c1",
        content=content,
    )


@pytest.mark.asyncio
async def test_publish_and_consume(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    await bus.publish_inbound(_make_msg("hello"))
    received = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert received.content == "hello"
    assert received.channel == "web"
    assert received.sender_id == "u1"


@pytest.mark.asyncio
async def test_consume_blocks_until_publish(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")

    async def _delayed_publish():
        await asyncio.sleep(0.05)
        await bus.publish_inbound(_make_msg("delayed"))

    asyncio.create_task(_delayed_publish())
    received = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert received.content == "delayed"


@pytest.mark.asyncio
async def test_rowid_stored_in_metadata(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    await bus.publish_inbound(_make_msg())
    received = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert "_bus_rowid" in received.metadata
    assert isinstance(received.metadata["_bus_rowid"], int)


@pytest.mark.asyncio
async def test_consume_sets_status_in_flight(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    db_path = tmp_path / "queue.db"
    bus = SqliteMessageBus(db_path)
    await bus.publish_inbound(_make_msg())
    await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("SELECT status FROM inbound_queue").fetchone()
    assert row[0] == "in_flight"


@pytest.mark.asyncio
async def test_ack_marks_done(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    db_path = tmp_path / "queue.db"
    bus = SqliteMessageBus(db_path)
    await bus.publish_inbound(_make_msg())
    received = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    await bus.ack_inbound(received)

    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("SELECT status FROM inbound_queue").fetchone()
    assert row[0] == "done"


@pytest.mark.asyncio
async def test_ack_noop_without_rowid(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    msg = _make_msg()  # no _bus_rowid in metadata
    await bus.ack_inbound(msg)  # must not raise


@pytest.mark.asyncio
async def test_replay_resets_in_flight(tmp_path):
    """Messages left in_flight (e.g. from a prior crash) are redelivered on replay."""
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    db_path = tmp_path / "queue.db"
    bus = SqliteMessageBus(db_path)
    await bus.publish_inbound(_make_msg("crash-survivor"))
    # consume but do NOT ack — simulates crash after dequeue
    await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    # Verify it's in_flight before replay
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute("SELECT status FROM inbound_queue").fetchone()[0] == "in_flight"

    # New bus instance (simulating restart)
    bus2 = SqliteMessageBus(db_path)
    await bus2.replay_pending()
    received = await asyncio.wait_for(bus2.consume_inbound(), timeout=1.0)
    assert received.content == "crash-survivor"


@pytest.mark.asyncio
async def test_replay_no_pending_no_error(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    await bus.replay_pending()  # empty DB — must not raise or hang


@pytest.mark.asyncio
async def test_preserves_media_and_metadata(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    msg = InboundMessage(
        channel="telegram",
        sender_id="u2",
        chat_id="c2",
        content="with media",
        media=["/tmp/photo.jpg"],
        metadata={"msg_id": 42},
    )
    await bus.publish_inbound(msg)
    received = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert received.media == ["/tmp/photo.jpg"]
    assert received.metadata["msg_id"] == 42


@pytest.mark.asyncio
async def test_preserves_session_key_override(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    msg = InboundMessage(
        channel="web",
        sender_id="u1",
        chat_id="c1",
        content="hi",
        session_key_override="bot:mybot:s:s_abc",
    )
    await bus.publish_inbound(msg)
    received = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert received.session_key_override == "bot:mybot:s:s_abc"
    assert received.session_key == "bot:mybot:s:s_abc"


@pytest.mark.asyncio
async def test_outbound_passthrough(tmp_path):
    from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus

    bus = SqliteMessageBus(tmp_path / "queue.db")
    out = OutboundMessage(channel="web", chat_id="c1", content="reply")
    await bus.publish_outbound(out)
    received = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert received.content == "reply"
