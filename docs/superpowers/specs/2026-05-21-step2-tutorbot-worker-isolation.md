# Step 2: TutorBot Worker Isolation Design

## Goal

Move each TutorBot's `AgentLoop` into its own `multiprocessing.Process` so that a slow or CPU-bound bot cannot starve other bots sharing the same asyncio event loop.

## Background

Step 1 (committed) added `SqliteMessageBus`: a per-bot SQLite-backed inbound queue with status lifecycle (`pending → in_flight → done`) and crash recovery (`replay_pending`). Step 2 builds on that foundation by introducing Redis Streams as the inter-process message bus and a `BotProcessManager` to spawn and supervise one worker process per bot.

## Architecture

```
┌─── Main process (FastAPI / uvicorn) ────────────────────────┐
│  ChannelManager   →  RedisMessageBus.publish_inbound()       │
│  WebSocket API    →  RedisMessageBus.publish_inbound()       │
│  OutboundRouter   ←  RedisMessageBus.consume_outbound()      │
│  BotProcessManager  (spawns / monitors worker processes)     │
└──────────────────────────────────────────────────────────────┘
          │ Redis Streams (XADD / XREADGROUP / XAUTOCLAIM)
┌─── Worker process per bot ──────────────────────────────────┐
│  RedisMessageBus.consume_inbound()  (XREADGROUP, blocking)   │
│  AgentLoop._dispatch() — LLM calls, tools, session writes    │
│  RedisMessageBus.publish_outbound() (XADD)                   │
└──────────────────────────────────────────────────────────────┘
```

### Redis Stream Keys

- **Inbound**: `bot:{bot_id}:inbound`
- **Outbound**: `bot:{bot_id}:outbound`
- Both trimmed with `MAXLEN ~ 1000` (approximate) to bound memory.

### Consumer Groups

Each bot's inbound stream has one consumer group named `cg:{bot_id}`. The worker uses `XREADGROUP GROUP cg:{bot_id} worker BLOCK 1000 COUNT 1` to wait for messages. `XAUTOCLAIM` after 60 s reclaims unacked messages from a dead consumer (crash recovery, replacing `replay_pending`).

## Components

### `deeptutor/tutorbot/bus/redis_bus.py` — `RedisMessageBus`

Drop-in replacement for `SqliteMessageBus`. Identical public interface:

| Method | Redis operation |
|--------|----------------|
| `publish_inbound(msg)` | `XADD bot:{id}:inbound MAXLEN ~ 1000 * <fields>` |
| `consume_inbound()` | `XREADGROUP` blocking; returns `InboundMessage` with `_bus_stream_id` stashed in `msg.metadata` |
| `ack_inbound(msg)` | `XACK bot:{id}:inbound cg:{id} <stream_id>` |
| `replay_pending()` | `XAUTOCLAIM` — reclaim messages idle >60 s back to this consumer |
| `publish_outbound(msg)` | `XADD bot:{id}:outbound MAXLEN ~ 1000 * <fields>` |
| `consume_outbound()` | `XREAD COUNT 1 BLOCK 1000 STREAMS bot:{id}:outbound <last_id>` |
| `inbound_size` (property) | `XLEN bot:{id}:inbound` |
| `outbound_size` (property) | `XLEN bot:{id}:outbound` |

Constructor: `RedisMessageBus(bot_id: str, redis_url: str)`. Creates consumer group with `MKSTREAM` on init.

Uses `redis.asyncio` (async client). All operations are native async — no `run_in_executor` needed.

### `deeptutor/tutorbot/worker/process.py` — worker entrypoint

```python
def worker_main(bot_id: str, workspace: Path, redis_url: str, config: dict) -> None:
    """Entry point for each bot worker process. Runs its own event loop."""
    asyncio.run(_async_worker_main(bot_id, workspace, redis_url, config))
```

`_async_worker_main`:
1. Instantiates `RedisMessageBus(bot_id, redis_url)`
2. Calls `bus.replay_pending()` (reclaim any in-flight from prior crash)
3. Instantiates `AgentLoop` with the bus and config
4. Runs `AgentLoop.run()` until SIGTERM
5. On SIGTERM: sets a stop flag, waits for the current `_dispatch` to finish, calls `bus.close()`

### `deeptutor/tutorbot/worker/manager.py` — `BotProcessManager`

Manages the lifecycle of all worker processes within the main process.

```python
class BotProcessManager:
    async def start(self, bot_id, workspace, redis_url, config) -> None
    async def stop(self, bot_id) -> None
    async def stop_all(self) -> None
    async def _health_loop(self) -> None   # runs as asyncio.Task
```

`_health_loop` checks `process.is_alive()` every 30 s. Dead processes are restarted with exponential backoff: 1 s → 2 s → 4 s → … → max 60 s. Backoff resets after 5 minutes of stable uptime.

Uses `multiprocessing.Process(target=worker_main, args=(...), daemon=True)` with `start_method='spawn'` (safe on Windows and Linux).

### `deeptutor/services/tutorbot/manager.py` — wire-up (modified)

`start_bot()` change:

```python
redis_url = os.getenv("REDIS_URL")
if redis_url:
    bus = RedisMessageBus(bot_id=bot_id, redis_url=redis_url)
    await bot_process_manager.start(bot_id, workspace, redis_url, bot_config)
else:
    bus = SqliteMessageBus(db_path=workspace / "queue.db")
    await bus.replay_pending()
    # existing asyncio task spawning unchanged
```

The `OutboundRouter` asyncio task in the main process polls `bus.consume_outbound()` and routes to `ChannelManager` or the active WebSocket session (unchanged routing logic, new bus source).

### `docker-compose.yml` — add Redis

```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes
```

Add `REDIS_URL: redis://redis:6379` to the backend service environment.

### `pyproject.toml` — dependencies

- `[tutorbot]` extras: add `redis[asyncio]>=5.0`
- `[dev]` extras: add `fakeredis[aioredis]>=2.0`

## Data Flow

**Channel message inbound:**
```
Telegram/Discord → ChannelManager (main) → RedisMessageBus.publish_inbound()
  → XADD bot:{id}:inbound
  → Worker XREADGROUP → AgentLoop._dispatch()
  → RedisMessageBus.publish_outbound() → XADD bot:{id}:outbound
  → OutboundRouter (main, polls ~100ms) → ChannelManager.send()
```

**Web UI message inbound:**
```
WebSocket → FastAPI handler → RedisMessageBus.publish_inbound()
  → [same worker path as above]
  → OutboundRouter → WebSocket.send_json()
```

## Error Handling

| Scenario | Handling |
|----------|---------|
| Worker crashes mid-message | XAUTOCLAIM after 60 s reclaims unacked message; `BotProcessManager` restarts with backoff |
| Redis goes down | `RedisMessageBus` raises `ConnectionError`; `BotProcessManager` catches, logs, retries with backoff; messages survive in stream once Redis recovers |
| Worker takes >60 s on one message | XAUTOCLAIM redelivers to restarted consumer; LLM calls are naturally retryable |
| Stream does not exist yet | `MKSTREAM` flag on consumer group creation handles this atomically |
| `REDIS_URL` not set | Falls back to `SqliteMessageBus` — single-process behaviour unchanged |
| Worker SIGTERM | Finishes current `_dispatch`, calls `XACK`, exits cleanly; `BotProcessManager` does not restart |

## Testing

All tests use `fakeredis` — no real Redis instance required in CI.

| File | Coverage |
|------|---------|
| `tests/tutorbot/test_redis_bus.py` | 11-test battery mirroring `test_sqlite_bus.py`: publish/consume round-trip, blocking until publish, XAUTOCLAIM crash recovery, ack marks done, outbound passthrough, media/metadata/session_key preserved |
| `tests/tutorbot/test_bot_process_manager.py` | Start worker (stub `worker_main`), stop cleanly, crash→auto-restart, backoff doubles on repeated crashes |

Integration (manual / Docker CI): spin up Redis, start one bot, publish inbound, assert outbound within 500 ms.

`tests/tutorbot/test_sqlite_bus.py` unchanged — fallback path stays green.

## Out of Scope

- Real-time token-by-token streaming to the browser (outbound is polled at ~100 ms)
- Multi-host Redis scaling (single-node Redis)
- Step 3 (horizontal scaling across hosts)
