"""SQLite-backed persistent inbound message bus."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from deeptutor.tutorbot.bus.events import InboundMessage, OutboundMessage

_ROWID_KEY = "_bus_rowid"

_DDL = """\
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS inbound_queue (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    channel              TEXT NOT NULL,
    sender_id            TEXT NOT NULL,
    chat_id              TEXT NOT NULL,
    content              TEXT NOT NULL,
    media_json           TEXT NOT NULL DEFAULT '[]',
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    attachments_json     TEXT,
    session_key_override TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_inbound_status ON inbound_queue(status, id);
"""


class SqliteMessageBus:
    """
    Drop-in replacement for MessageBus with SQLite-backed inbound persistence.

    Inbound status lifecycle:
        pending   – written by publish_inbound, awaiting consume
        in_flight – claimed by consume_inbound, processing
        done      – acked by ack_inbound after successful dispatch

    On restart: call replay_pending() once; it resets any in_flight rows
    back to pending so they are redelivered.

    Outbound queue is in-memory (asyncio.Queue) — no persistence needed.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._event = asyncio.Event()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path)) as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def replay_pending(self) -> None:
        """Reset in_flight → pending. Call once at bot startup before tasks begin."""
        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(None, self._sync_replay)
        if count > 0:
            self._event.set()

    def _sync_replay(self) -> int:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE inbound_queue SET status='pending' WHERE status='in_flight'"
            )
            conn.commit()
            return conn.execute(
                "SELECT COUNT(*) FROM inbound_queue WHERE status='pending'"
            ).fetchone()[0]

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def publish_inbound(self, msg: InboundMessage) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_insert, msg)
        self._event.set()

    def _sync_insert(self, msg: InboundMessage) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT INTO inbound_queue
                    (channel, sender_id, chat_id, content,
                     media_json, metadata_json, attachments_json,
                     session_key_override, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    msg.channel,
                    msg.sender_id,
                    msg.chat_id,
                    msg.content,
                    json.dumps(msg.media),
                    json.dumps(msg.metadata),
                    json.dumps(msg.attachments) if msg.attachments is not None else None,
                    msg.session_key_override,
                ),
            )
            conn.commit()

    async def consume_inbound(self) -> InboundMessage:
        """Block until a pending message is available, claim it, return it."""
        loop = asyncio.get_running_loop()
        while True:
            await self._event.wait()
            row = await loop.run_in_executor(None, self._sync_claim)
            if row is None:
                self._event.clear()
                continue
            return self._row_to_msg(row)

    def _sync_claim(self) -> tuple | None:
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                """
                SELECT id, channel, sender_id, chat_id, content,
                       media_json, metadata_json, attachments_json,
                       session_key_override
                FROM inbound_queue
                WHERE status = 'pending'
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE inbound_queue SET status='in_flight' WHERE id=?",
                (row[0],),
            )
            conn.commit()
            return row

    def _row_to_msg(self, row: tuple) -> InboundMessage:
        (
            row_id, channel, sender_id, chat_id, content,
            media_json, meta_json, att_json, sk_override,
        ) = row
        metadata: dict = json.loads(meta_json) if meta_json else {}
        metadata[_ROWID_KEY] = row_id
        return InboundMessage(
            channel=channel,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=json.loads(media_json) if media_json else [],
            metadata=metadata,
            attachments=json.loads(att_json) if att_json is not None else None,
            session_key_override=sk_override,
        )

    async def ack_inbound(self, msg: InboundMessage) -> None:
        """Mark message as done. No-op if msg has no _bus_rowid in metadata."""
        row_id = msg.metadata.get(_ROWID_KEY)
        if row_id is None:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_ack, row_id)

    def _sync_ack(self, row_id: int) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE inbound_queue SET status='done' WHERE id=?",
                (row_id,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Outbound (in-memory, no persistence)
    # ------------------------------------------------------------------

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self._outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        return await self._outbound.get()

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    @property
    def inbound_size(self) -> int:
        with sqlite3.connect(str(self._db_path)) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM inbound_queue WHERE status IN ('pending','in_flight')"
            ).fetchone()[0]

    @property
    def outbound_size(self) -> int:
        return self._outbound.qsize()
