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
