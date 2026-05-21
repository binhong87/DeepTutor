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
