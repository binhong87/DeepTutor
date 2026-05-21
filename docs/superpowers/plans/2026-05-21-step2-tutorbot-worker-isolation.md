# Step 2: TutorBot Worker Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move each TutorBot's AgentLoop into its own `multiprocessing.Process` backed by Redis Streams so a slow bot cannot starve others in the shared asyncio event loop.

**Architecture:** Main process runs FastAPI, ChannelManager, and an OutboundRouter that consumes from Redis. Each worker process runs an isolated asyncio event loop with AgentLoop and its own `RedisMessageBus` instance; the two sides communicate through `bot:{id}:inbound` and `bot:{id}:outbound` Redis Streams. When `REDIS_URL` is not set, the existing `SqliteMessageBus` single-process path is unchanged.

**Tech Stack:** `redis[asyncio]>=5.0`, `fakeredis[aioredis]>=2.0` (tests), `multiprocessing` (stdlib), Redis 7 Alpine (Docker)

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `deeptutor/tutorbot/bus/redis_bus.py` | `RedisMessageBus` — drop-in for `SqliteMessageBus` |
| Create | `deeptutor/tutorbot/worker/__init__.py` | package marker |
| Create | `deeptutor/tutorbot/worker/process.py` | `worker_main` — spawned process entrypoint |
| Create | `deeptutor/tutorbot/worker/manager.py` | `BotProcessManager` — spawn/monitor/restart |
| Create | `tests/tutorbot/test_redis_bus.py` | 11-test battery with fakeredis |
| Create | `tests/tutorbot/test_bot_process_manager.py` | lifecycle tests |
| Modify | `deeptutor/services/tutorbot/manager.py` | wire Redis path in `start_bot`; add `bus` field to `TutorBotInstance` |
| Modify | `pyproject.toml` | add `redis[asyncio]` and `fakeredis` deps |
| Modify | `docker-compose.yml` | add Redis service + `REDIS_URL` env var |

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add redis deps to pyproject.toml**

In `pyproject.toml`, under `[project.optional-dependencies]`:

```toml
tutorbot = [
    "deeptutor[server]",
    "croniter>=6.0.0,<7.0.0",
    "tiktoken>=0.12.0,<1.0.0",
    "chardet>=3.0.2,<6.0.0",
    "mcp>=1.26.0,<2.0.0",
    "readability-lxml>=0.8.4,<1.0.0",
    "python-telegram-bot[socks]>=22.6,<23.0",
    "lark-oapi>=1.5.0,<2.0.0",
    "dingtalk-stream>=0.24.0,<1.0.0",
    "slack-sdk>=3.39.0,<4.0.0",
    "slackify-markdown>=0.2.0,<1.0.0",
    "qq-botpy>=1.2.0,<2.0.0",
    "python-socketio>=5.16.0,<6.0.0",
    "msgpack>=1.1.0,<2.0.0",
    "python-socks[asyncio]>=2.8.0,<3.0.0",
    "socksio>=1.0.0,<2.0.0",
    "websocket-client>=1.9.0,<2.0.0",
    "redis[asyncio]>=5.0,<6.0",
]

dev = [
    "deeptutor[server]",
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pre-commit>=3.0.0",
    "safety<3.0.0",
    "bandit>=1.8.0",
    "fakeredis[aioredis]>=2.0,<3.0",
]
```

- [ ] **Step 2: Add Redis service to docker-compose.yml**

Add after the `pocketbase` service and before `deeptutor`, add a new `volumes` key at the bottom:

```yaml
  redis:
    image: redis:7-alpine
    container_name: deeptutor-redis
    restart: unless-stopped
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    networks:
      - deeptutor-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
```

In the `deeptutor` service `environment:` block, add:
```yaml
      - REDIS_URL=${REDIS_URL:-redis://redis:6379}
```

In the `deeptutor` service `depends_on:` block, add:
```yaml
      redis:
        condition: service_healthy
```

At the bottom of the file, add `volumes:` section:
```yaml
volumes:
  redis_data:
```

- [ ] **Step 3: Install deps**

```bash
pip install -e ".[tutorbot,dev]"
```

Expected: installs `redis` and `fakeredis` without errors.

- [ ] **Step 4: Smoke check**

```bash
python -c "import redis.asyncio; import fakeredis; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docker-compose.yml
git commit -m "feat(deps): add redis[asyncio] and fakeredis for TutorBot worker isolation"
```

---

## Task 2: Write failing tests for RedisMessageBus

**Files:**
- Create: `tests/tutorbot/test_redis_bus.py`

- [ ] **Step 1: Write the full test file**

Create `tests/tutorbot/test_redis_bus.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q --import-mode=importlib tests/tutorbot/test_redis_bus.py 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError: deeptutor.tutorbot.bus.redis_bus`

---

## Task 3: Implement RedisMessageBus

**Files:**
- Create: `deeptutor/tutorbot/bus/redis_bus.py`

- [ ] **Step 1: Create the file**

Create `deeptutor/tutorbot/bus/redis_bus.py`:

```python
"""Redis Streams-backed message bus for per-bot worker process isolation."""
from __future__ import annotations

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
            # First drain any reclaimed messages (id="0" = "my pending entries")
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

            # Then block for new messages (id=">" = "never delivered to any consumer")
            results = await r.xreadgroup(
                self._group,
                self._consumer,
                {self._inbound_key: ">"},
                count=1,
                block=1000,
            )
            if results:
                _, messages = results[0]
                stream_id, fields = messages[0]
                return self._fields_to_inbound(stream_id, fields)

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
        """Reclaim messages idle longer than min_idle_time_ms back to this consumer."""
        r = await self._get_redis()
        try:
            await r.xautoclaim(
                self._inbound_key,
                self._group,
                self._consumer,
                min_idle_time=min_idle_time_ms,
                start_id="0-0",
            )
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
                block=1000,
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
```

- [ ] **Step 2: Run tests**

```bash
pytest -q --import-mode=importlib tests/tutorbot/test_redis_bus.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 3: Commit**

```bash
git add deeptutor/tutorbot/bus/redis_bus.py tests/tutorbot/test_redis_bus.py
git commit -m "feat(tutorbot): RedisMessageBus backed by Redis Streams"
```

---

## Task 4: Worker package scaffold

**Files:**
- Create: `deeptutor/tutorbot/worker/__init__.py`

- [ ] **Step 1: Create package marker**

Create `deeptutor/tutorbot/worker/__init__.py` with content:

```python
"""TutorBot worker-process package."""
```

- [ ] **Step 2: Verify import**

```bash
python -c "import deeptutor.tutorbot.worker; print('OK')"
```

Expected: `OK`

---

## Task 5: Write failing tests for BotProcessManager

**Files:**
- Create: `tests/tutorbot/test_bot_process_manager.py`

- [ ] **Step 1: Write the test file**

Create `tests/tutorbot/test_bot_process_manager.py`:

```python
"""Tests for BotProcessManager — process lifecycle and health monitoring."""
from __future__ import annotations

import asyncio
import multiprocessing
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _instant_worker(bot_id, workspace, redis_url, config):
    """Stub worker that exits immediately — used to test lifecycle."""
    pass


def _slow_worker(bot_id, workspace, redis_url, config):
    """Stub worker that sleeps until terminated."""
    time.sleep(60)


@pytest.mark.asyncio
async def test_start_spawns_process():
    from deeptutor.tutorbot.worker.manager import BotProcessManager

    mgr = BotProcessManager()
    with patch("deeptutor.tutorbot.worker.manager.worker_main", _instant_worker):
        await mgr.start("bot1", Path("/tmp"), "redis://localhost", {})
    assert "bot1" in mgr._entries
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_stop_terminates_process():
    from deeptutor.tutorbot.worker.manager import BotProcessManager

    mgr = BotProcessManager()
    with patch("deeptutor.tutorbot.worker.manager.worker_main", _slow_worker):
        await mgr.start("bot1", Path("/tmp"), "redis://localhost", {})
        proc = mgr._entries["bot1"].process
        assert proc.is_alive()
        await mgr.stop("bot1")
        assert not proc.is_alive()


@pytest.mark.asyncio
async def test_stop_all_terminates_all():
    from deeptutor.tutorbot.worker.manager import BotProcessManager

    mgr = BotProcessManager()
    with patch("deeptutor.tutorbot.worker.manager.worker_main", _slow_worker):
        await mgr.start("bot1", Path("/tmp"), "redis://localhost", {})
        await mgr.start("bot2", Path("/tmp"), "redis://localhost", {})
        procs = [mgr._entries[b].process for b in ["bot1", "bot2"]]
        await mgr.stop_all()
    for p in procs:
        assert not p.is_alive()


@pytest.mark.asyncio
async def test_health_loop_restarts_dead_process():
    from deeptutor.tutorbot.worker.manager import BotProcessManager, _BotEntry

    mgr = BotProcessManager()
    restart_calls: list[str] = []

    async def mock_restart(entry: _BotEntry) -> None:
        restart_calls.append(entry.bot_id)
        alive = MagicMock()
        alive.is_alive.return_value = True
        entry.process = alive  # mark alive so loop doesn't restart again

    mgr._restart_entry = mock_restart

    entry = _BotEntry("bot1", Path("/tmp"), "redis://localhost", {})
    dead_proc = MagicMock()
    dead_proc.is_alive.return_value = False
    entry.process = dead_proc
    entry.last_start = time.monotonic()
    mgr._entries["bot1"] = entry

    mgr._HEALTH_INTERVAL = 0.02  # speed up the health check for tests
    health_task = asyncio.create_task(mgr._health_loop())
    await asyncio.sleep(0.15)  # let at least one cycle run
    mgr._stopping = True
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass

    assert "bot1" in restart_calls, "health loop must restart a dead bot"


@pytest.mark.asyncio
async def test_backoff_doubles_on_repeated_crash():
    from unittest.mock import AsyncMock, patch

    from deeptutor.tutorbot.worker.manager import BotProcessManager, _BotEntry

    mgr = BotProcessManager()
    spawn_calls = 0

    def mock_spawn(e):
        nonlocal spawn_calls
        spawn_calls += 1
        dead = MagicMock()
        dead.is_alive.return_value = False
        e.process = dead
        e.last_start = time.monotonic()

    mgr._spawn = mock_spawn
    entry = _BotEntry("bot1", Path("/tmp"), "redis://localhost", {})
    dead = MagicMock()
    dead.is_alive.return_value = False
    entry.process = dead
    entry.last_start = time.monotonic()
    mgr._entries["bot1"] = entry

    with patch("deeptutor.tutorbot.worker.manager.asyncio.sleep", new_callable=AsyncMock):
        await mgr._restart_entry(entry)  # backoff 1→2
        assert entry.backoff == 2.0
        await mgr._restart_entry(entry)  # backoff 2→4
        assert entry.backoff == 4.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q --import-mode=importlib tests/tutorbot/test_bot_process_manager.py 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError: deeptutor.tutorbot.worker.manager`

---

## Task 6: Implement worker/process.py

**Files:**
- Create: `deeptutor/tutorbot/worker/process.py`

- [ ] **Step 1: Create the file**

Create `deeptutor/tutorbot/worker/process.py`:

```python
"""Worker process entrypoint — each TutorBot runs here in isolation."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def worker_main(bot_id: str, workspace: Path, redis_url: str, config: dict) -> None:
    """Entrypoint called by multiprocessing.Process. Runs its own event loop."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_async_main(bot_id, workspace, redis_url, config))


async def _async_main(bot_id: str, workspace: Path, redis_url: str, config: dict) -> None:
    from deeptutor.services.tutorbot.manager import BotConfig
    from deeptutor.services.tutorbot.model_runtime import resolve_tutorbot_llm_config
    from deeptutor.tutorbot.agent.loop import AgentLoop
    from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus
    from deeptutor.tutorbot.config.schema import ExecToolConfig
    from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
    from deeptutor.tutorbot.session.manager import SessionManager

    stop_event = asyncio.Event()

    def _on_sigterm(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _on_sigterm)

    bus = RedisMessageBus(bot_id=bot_id, redis_url=redis_url)
    await bus.replay_pending()

    bot_config = BotConfig(**config) if config else BotConfig(name=bot_id)
    llm_config = resolve_tutorbot_llm_config(bot_config)
    provider = create_deeptutor_provider(llm_config)
    session_adapter = SessionManager(workspace)
    venv_bin = str(Path(sys.executable).parent)
    exec_config = ExecToolConfig(timeout=300, path_append=venv_bin)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=llm_config.model,
        context_window_tokens=llm_config.context_window or 65_536,
        exec_config=exec_config,
        session_manager=session_adapter,
        default_session_key=f"bot:{bot_id}",
    )

    loop_task = asyncio.create_task(agent_loop.run(), name=f"worker:{bot_id}:loop")
    stop_task = asyncio.create_task(stop_event.wait(), name=f"worker:{bot_id}:stop")

    await asyncio.wait([loop_task, stop_task], return_when=asyncio.FIRST_COMPLETED)

    agent_loop.stop()
    for task in [loop_task, stop_task]:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    await bus.close()
    logger.info("Worker for bot '%s' shut down cleanly", bot_id)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from deeptutor.tutorbot.worker.process import worker_main; print('OK')"
```

Expected: `OK`

---

## Task 7: Implement BotProcessManager

**Files:**
- Create: `deeptutor/tutorbot/worker/manager.py`

- [ ] **Step 1: Create the file**

Create `deeptutor/tutorbot/worker/manager.py`:

```python
"""BotProcessManager — spawn, monitor, and restart per-bot worker processes."""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 60.0
_BACKOFF_RESET_AFTER = 300.0  # 5 minutes of uptime resets backoff


@dataclass
class _BotEntry:
    bot_id: str
    workspace: Path
    redis_url: str
    config: dict
    process: multiprocessing.Process | None = field(default=None, repr=False)
    backoff: float = _BACKOFF_INITIAL
    last_start: float = field(default_factory=time.monotonic)


# Importable by tests that need to patch it
from deeptutor.tutorbot.worker.process import worker_main  # noqa: E402


class BotProcessManager:
    """Spawn and supervise one worker process per TutorBot."""

    _HEALTH_INTERVAL: float = 30.0

    def __init__(self) -> None:
        self._entries: dict[str, _BotEntry] = {}
        self._health_task: asyncio.Task | None = None
        self._stopping: bool = False
        ctx = multiprocessing.get_context("spawn")
        self._mp_context = ctx

    async def start(
        self, bot_id: str, workspace: Path, redis_url: str, config: dict
    ) -> None:
        entry = _BotEntry(
            bot_id=bot_id, workspace=workspace, redis_url=redis_url, config=config
        )
        self._entries[bot_id] = entry
        self._spawn(entry)
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(
                self._health_loop(), name="bot-process-health"
            )

    def _spawn(self, entry: _BotEntry) -> None:
        p = self._mp_context.Process(
            target=worker_main,
            args=(entry.bot_id, entry.workspace, entry.redis_url, entry.config),
            daemon=True,
            name=f"tutorbot-worker-{entry.bot_id}",
        )
        p.start()
        entry.process = p
        entry.last_start = time.monotonic()
        logger.info(
            "Spawned worker for bot '%s' (pid=%s)", entry.bot_id, p.pid
        )

    async def stop(self, bot_id: str) -> None:
        entry = self._entries.pop(bot_id, None)
        if entry is None:
            return
        await self._kill_process(entry)

    async def stop_all(self) -> None:
        self._stopping = True
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        for bot_id in list(self._entries.keys()):
            entry = self._entries.pop(bot_id, None)
            if entry:
                await self._kill_process(entry)

    async def _kill_process(self, entry: _BotEntry) -> None:
        p = entry.process
        if p is None or not p.is_alive():
            return
        p.terminate()
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, p.join, 30), timeout=35
            )
        except (asyncio.TimeoutError, Exception):
            pass
        if p.is_alive():
            p.kill()
        logger.info("Stopped worker for bot '%s'", entry.bot_id)

    async def _restart_entry(self, entry: _BotEntry) -> None:
        logger.warning(
            "Bot '%s' worker died; restarting in %.0fs (backoff)",
            entry.bot_id,
            entry.backoff,
        )
        await asyncio.sleep(entry.backoff)
        entry.backoff = min(entry.backoff * 2, _BACKOFF_MAX)
        self._spawn(entry)

    async def _health_loop(self) -> None:
        try:
            while not self._stopping:
                await asyncio.sleep(self._HEALTH_INTERVAL)
                now = time.monotonic()
                for entry in list(self._entries.values()):
                    if entry.process is None or not entry.process.is_alive():
                        if now - entry.last_start >= _BACKOFF_RESET_AFTER:
                            entry.backoff = _BACKOFF_INITIAL
                        await self._restart_entry(entry)
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 2: Run tests**

```bash
pytest -q --import-mode=importlib tests/tutorbot/test_bot_process_manager.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add deeptutor/tutorbot/worker/ tests/tutorbot/test_bot_process_manager.py
git commit -m "feat(tutorbot): BotWorkerProcess entrypoint and BotProcessManager"
```

---

## Task 8: Wire Redis path into manager.py

**Files:**
- Modify: `deeptutor/services/tutorbot/manager.py`

The key changes:

1. Add `bus: Any = None` field to `TutorBotInstance` (so `reload_channels` can use `instance.bus` instead of `instance.agent_loop.bus`)
2. In `start_bot()`: when `REDIS_URL` is set, create `RedisMessageBus`, spawn worker via `BotProcessManager`, skip AgentLoop asyncio task in main process
3. Add a `_bot_process_manager` attribute to `TutorBotManager`
4. Fix `reload_channels` to use `instance.bus`

- [ ] **Step 1: Add `bus` field to `TutorBotInstance` and `_bot_process_manager` to `TutorBotManager`**

In `manager.py`, find `TutorBotInstance` dataclass (line ~229) and add `bus: Any = None` after `agent_loop`:

```python
@dataclass
class TutorBotInstance:
    """A running TutorBot and its metadata."""

    bot_id: str
    config: BotConfig
    owner_id: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    tasks: list[asyncio.Task] = field(default_factory=list, repr=False)
    agent_loop: Any = None
    bus: Any = None          # ← ADD THIS LINE
    channel_manager: Any = None
    heartbeat: Any = None
    notify_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    channel_bindings: dict[str, str] = field(default_factory=dict)
    reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    last_reload_error: str | None = None
```

- [ ] **Step 2: Add `_bot_process_manager` to `TutorBotManager.__init__`**

Find `TutorBotManager.__init__` and add after `self._bots`:

```python
        from deeptutor.tutorbot.worker.manager import BotProcessManager
        self._bot_process_manager = BotProcessManager()
```

- [ ] **Step 3: Replace the bus creation block in `start_bot()`**

Find these lines in `start_bot()` (around line 516–528):

```python
        from deeptutor.services.tutorbot.model_runtime import (
            resolve_tutorbot_llm_config,
        )
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus
        from deeptutor.tutorbot.config.schema import ExecToolConfig
        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
        from deeptutor.tutorbot.session.manager import SessionManager

        llm_config = resolve_tutorbot_llm_config(config)
        provider = create_deeptutor_provider(llm_config)
        bus = SqliteMessageBus(db_path=workspace / "queue.db")
        await bus.replay_pending()
```

Replace with:

```python
        import os

        from deeptutor.services.tutorbot.model_runtime import (
            resolve_tutorbot_llm_config,
        )
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus
        from deeptutor.tutorbot.config.schema import ExecToolConfig
        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
        from deeptutor.tutorbot.session.manager import SessionManager

        redis_url = os.getenv("REDIS_URL")
        llm_config = resolve_tutorbot_llm_config(config)
        provider = create_deeptutor_provider(llm_config)

        if redis_url:
            from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus
            bus = RedisMessageBus(bot_id=bot_id, redis_url=redis_url)
            await bus.replay_pending()
        else:
            bus = SqliteMessageBus(db_path=workspace / "queue.db")
            await bus.replay_pending()
```

- [ ] **Step 4: Skip AgentLoop tasks in main process when using Redis**

Find the block that builds `agent_loop` and the `loop_task` creation (around line 542–574). Replace from `workspace = self._bot_workspace(bot_id)` through the `loop_task = asyncio.create_task(...)` line:

```python
        workspace = self._bot_workspace(bot_id)
        session_adapter = SessionManager(workspace)

        if config.persona:
            soul_path = workspace / "SOUL.md"
            soul_path.write_text(config.persona, encoding="utf-8")

        venv_bin = str(Path(sys.executable).parent)
        exec_config = ExecToolConfig(timeout=300, path_append=venv_bin)

        canonical_key = f"bot:{bot_id}"

        if redis_url:
            # AgentLoop runs in a worker process — do not create it in main process
            agent_loop = None
        else:
            agent_loop = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=workspace,
                model=llm_config.model,
                context_window_tokens=llm_config.context_window or 65_536,
                exec_config=exec_config,
                session_manager=session_adapter,
                user_memory_dir=self._memory_dir,
                user_id=self._scope.user_id,
                restrict_to_workspace=False,
                default_session_key=canonical_key,
            )
```

- [ ] **Step 5: Replace core tasks block to conditionally spawn worker**

Find the block starting `# -- Core tasks ---` (around line 571):

```python
        # -- Core tasks -------------------------------------------------------
        loop_task = asyncio.create_task(
            agent_loop.run(),
            name=f"tutorbot:{bot_id}:loop",
        )
        router_task = asyncio.create_task(
            self._outbound_router(bot_id, bus, instance),
            name=f"tutorbot:{bot_id}:router",
        )
        instance.tasks.extend([loop_task, router_task])
```

Replace with:

```python
        # -- Core tasks -------------------------------------------------------
        if redis_url:
            # Worker process handles AgentLoop; main process only routes outbound
            import dataclasses as _dc
            config_dict = _dc.asdict(config) if _dc.is_dataclass(config) else dict(vars(config))
            await self._bot_process_manager.start(
                bot_id, workspace, redis_url, config_dict
            )
        else:
            loop_task = asyncio.create_task(
                agent_loop.run(),
                name=f"tutorbot:{bot_id}:loop",
            )
            instance.tasks.append(loop_task)

        router_task = asyncio.create_task(
            self._outbound_router(bot_id, bus, instance),
            name=f"tutorbot:{bot_id}:router",
        )
        instance.tasks.append(router_task)
```

- [ ] **Step 6: Store bus on instance and skip heartbeat in Redis mode**

After the `instance = TutorBotInstance(...)` construction (around line 563), add:

```python
        instance.bus = bus
```

Then find the heartbeat block (around line 590–613). Wrap it so it only runs in non-Redis mode:

```python
        if not redis_url:
            from deeptutor.tutorbot.heartbeat import HeartbeatService

            async def _hb_execute(tasks_summary: str) -> str:
                return await agent_loop.process_direct(
                    tasks_summary,
                    session_key=canonical_key,
                    channel="web",
                    chat_id="web",
                )

            async def _hb_notify(response: str) -> None:
                await instance.notify_queue.put(response)

            heartbeat = HeartbeatService(
                workspace=workspace,
                provider=provider,
                model=agent_loop.model,
                on_execute=_hb_execute,
                on_notify=_hb_notify,
                interval_s=30 * 60,
            )
            instance.heartbeat = heartbeat
            await heartbeat.start()
```

- [ ] **Step 7: Fix `reload_channels` to use `instance.bus`**

Find the line in `reload_channels` (around line 798):

```python
                channel_manager = self._build_channel_manager(
                    instance.config,
                    instance.agent_loop.bus,
                    bot_id=bot_id,
                )
```

Replace with:

```python
                _bus = instance.bus or (instance.agent_loop.bus if instance.agent_loop else None)
                channel_manager = self._build_channel_manager(
                    instance.config,
                    _bus,
                    bot_id=bot_id,
                )
```

- [ ] **Step 8: Stop worker processes when bot stops**

Find `stop_bot()` (around line 701). Before the tasks cancellation loop, add:

```python
        import os
        if os.getenv("REDIS_URL"):
            await self._bot_process_manager.stop(bot_id)
```

- [ ] **Step 9: Smoke test**

```bash
python -c "from deeptutor.services.tutorbot.manager import TutorBotManager; print('OK')"
```

Expected: `OK`

- [ ] **Step 10: Run tutorbot tests**

```bash
pytest -q --import-mode=importlib tests/tutorbot/ -v
```

Expected: all tests pass (including the existing 28 + new 16).

- [ ] **Step 11: Commit**

```bash
git add deeptutor/services/tutorbot/manager.py
git commit -m "feat(tutorbot): wire RedisMessageBus + BotProcessManager into start_bot"
```

---

## Task 9: Final verification

- [ ] **Step 1: Full import smoke check**

```bash
python -c "
from deeptutor.runtime.orchestrator import ChatOrchestrator
from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus
from deeptutor.tutorbot.worker.process import worker_main
from deeptutor.tutorbot.worker.manager import BotProcessManager
from deeptutor.services.tutorbot.manager import TutorBotManager
print('all imports OK')
"
```

Expected: `all imports OK`

- [ ] **Step 2: Run all tutorbot tests**

```bash
pytest -q --import-mode=importlib tests/tutorbot/ -v
```

Expected: all pass.

- [ ] **Step 3: Run existing smoke suite**

```bash
pytest -q --import-mode=importlib \
  tests/api tests/cli tests/services/test_model_catalog.py \
  tests/services/test_path_service.py tests/services/memory \
  tests/services/session tests/tools
```

Expected: same pass/fail count as before these changes (no regressions).

- [ ] **Step 4: Commit**

If any stray files were added:

```bash
git add -A
git commit -m "chore(tutorbot): final cleanup for Step 2 worker isolation"
```
