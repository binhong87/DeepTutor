"""Redis Streams-backed message bus for per-bot worker process isolation."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from deeptutor.tutorbot.bus.events import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)

_STREAM_ID_KEY = "_bus_stream_id"
_MAXLEN = 1000


class RedisMessageBus:
    """
    Drop-in replacement for SqliteMessageBus using Redis Streams.

    Two separate instances share the same Redis keys:
      - Worker process: consume_inbound() + publish_outbound()
      - Main process:   publish_inbound() + consume_outbound()

    Stream keys:  bot:{bot_id}:inbound   bot:{bot_id}:outbound
    Consumer group: cg:{bot_id}  (inbound only; outbound uses plain XREAD)
    """

    def __init__(
        self,
        bot_id: str,
        redis_url: str,
        *,
        _redis: Any = None,
        _initial_outbound_id: str = "$",
    ) -> None:
        self._bot_id = bot_id
        self._redis_url = redis_url
        self._inbound_key = f"bot:{bot_id}:inbound"
        self._outbound_key = f"bot:{bot_id}:outbound"
        self._group = f"cg:{bot_id}"
        self._consumer = "worker"
        self._redis: Any = _redis  # injected in tests; None = create from redis_url
        self._last_outbound_id: str = _initial_outbound_id
        self._group_created = False  # created lazily on first _get_redis call
        # Buffer populated by replay_pending; drained first in consume_inbound.
        # Needed because fakeredis xautoclaim returns messages directly but they
        # are not visible to a subsequent xreadgroup(id="0") via a different
        # client instance (a fakeredis limitation that real Redis doesn't share).
        self._reclaim_buffer: list[tuple[str, dict]] = []

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Any:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        if not self._group_created:
            await self._ensure_group()
            self._group_created = True
        return self._redis

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._inbound_key, self._group, id="0", mkstream=True
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def publish_inbound(self, msg: InboundMessage) -> None:
        r = await self._get_redis()
        await r.xadd(
            self._inbound_key,
            {
                "channel": msg.channel,
                "sender_id": msg.sender_id,
                "chat_id": msg.chat_id,
                "content": msg.content,
                "media_json": json.dumps(msg.media),
                "metadata_json": json.dumps(
                    {k: v for k, v in msg.metadata.items() if k != _STREAM_ID_KEY}
                ),
                "attachments_json": json.dumps(msg.attachments)
                if msg.attachments is not None
                else "",
                "session_key_override": msg.session_key_override or "",
            },
            maxlen=_MAXLEN,
            approximate=True,
        )

    async def consume_inbound(self) -> InboundMessage:
        r = await self._get_redis()
        while True:
            # Drain messages reclaimed by replay_pending (works around a
            # fakeredis limitation where xautoclaim results are not visible to
            # xreadgroup(id="0") via a different client instance).
            if self._reclaim_buffer:
                stream_id, fields = self._reclaim_buffer.pop(0)
                return self._fields_to_inbound(stream_id, fields)

            # Drain pending messages already delivered but not yet acked.
            results = await r.xreadgroup(
                self._group,
                self._consumer,
                {self._inbound_key: "0"},
                count=1,
            )
            if results and results[0][1]:
                _, messages = results[0]
                stream_id, fields = messages[0]
                return self._fields_to_inbound(stream_id, fields)

            # Wait for new messages (id=">" = never delivered to any consumer).
            # block=100 keeps real-Redis efficient; fakeredis ignores it and
            # returns immediately, so we add asyncio.sleep(0) to yield the
            # event loop on each empty pass (prevents tight spin).
            results = await r.xreadgroup(
                self._group,
                self._consumer,
                {self._inbound_key: ">"},
                count=1,
                block=100,
            )
            if results:
                _, messages = results[0]
                stream_id, fields = messages[0]
                return self._fields_to_inbound(stream_id, fields)
            await asyncio.sleep(0)

    def _fields_to_inbound(self, stream_id: str, fields: dict) -> InboundMessage:
        metadata: dict = json.loads(fields.get("metadata_json") or "{}")
        metadata[_STREAM_ID_KEY] = stream_id
        att_raw = fields.get("attachments_json") or ""
        return InboundMessage(
            channel=fields["channel"],
            sender_id=fields["sender_id"],
            chat_id=fields["chat_id"],
            content=fields["content"],
            media=json.loads(fields.get("media_json") or "[]"),
            metadata=metadata,
            attachments=json.loads(att_raw) if att_raw else None,
            session_key_override=fields.get("session_key_override") or None,
        )

    async def ack_inbound(self, msg: InboundMessage) -> None:
        stream_id = msg.metadata.get(_STREAM_ID_KEY)
        if not stream_id:
            return
        r = await self._get_redis()
        await r.xack(self._inbound_key, self._group, stream_id)

    async def replay_pending(self, *, min_idle_time_ms: int = 60_000) -> None:
        """Reclaim messages idle longer than min_idle_time_ms back to this consumer.

        Reclaimed messages are pushed into _reclaim_buffer so consume_inbound()
        can find them even when xreadgroup(id="0") doesn't surface them (a
        known limitation of the fakeredis in-process mock).
        """
        r = await self._get_redis()
        try:
            result = await r.xautoclaim(
                self._inbound_key,
                self._group,
                self._consumer,
                min_idle_time=min_idle_time_ms,
                start_id="0-0",
            )
            # result: [next_start_id, [(stream_id, fields), ...], [deleted_ids]]
            if result and len(result) >= 2 and result[1]:
                for stream_id, fields in result[1]:
                    self._reclaim_buffer.append((stream_id, fields))
        except aioredis.ResponseError:
            pass  # stream may not exist yet on a fresh bot

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        r = await self._get_redis()
        await r.xadd(
            self._outbound_key,
            {
                "channel": msg.channel,
                "chat_id": msg.chat_id,
                "content": msg.content,
                "reply_to": msg.reply_to or "",
                "media_json": json.dumps(msg.media),
                "metadata_json": json.dumps(msg.metadata),
            },
            maxlen=_MAXLEN,
            approximate=True,
        )

    async def consume_outbound(self) -> OutboundMessage:
        r = await self._get_redis()
        while True:
            results = await r.xread(
                {self._outbound_key: self._last_outbound_id},
                count=1,
                block=100,
            )
            if results:
                _, messages = results[0]
                stream_id, fields = messages[0]
                self._last_outbound_id = stream_id
                return OutboundMessage(
                    channel=fields["channel"],
                    chat_id=fields["chat_id"],
                    content=fields["content"],
                    reply_to=fields.get("reply_to") or None,
                    media=json.loads(fields.get("media_json") or "[]"),
                    metadata=json.loads(fields.get("metadata_json") or "{}"),
                )
            await asyncio.sleep(0)

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    @property
    def inbound_size(self) -> int:
        import redis as _sync_redis

        r = _sync_redis.from_url(self._redis_url, decode_responses=True)
        try:
            return r.xlen(self._inbound_key)
        finally:
            r.close()

    @property
    def outbound_size(self) -> int:
        import redis as _sync_redis

        r = _sync_redis.from_url(self._redis_url, decode_responses=True)
        try:
            return r.xlen(self._outbound_key)
        finally:
            r.close()
