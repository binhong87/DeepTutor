"""Concurrency: two bots for one user must not interleave PROFILE.md writes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.tutorbot.agent.memory import _memory_lock


def test_memory_lock_is_per_directory(tmp_path: Path) -> None:
    a = tmp_path / "u_alice" / "memory"
    b = tmp_path / "u_bob" / "memory"
    a.mkdir(parents=True)
    b.mkdir(parents=True)

    lock_a = _memory_lock(a)
    lock_b = _memory_lock(b)
    lock_a_again = _memory_lock(a)

    assert lock_a is lock_a_again
    assert lock_a is not lock_b


@pytest.mark.asyncio
async def test_concurrent_consolidation_is_serialized(tmp_path: Path) -> None:
    """Two consolidate() calls under the same memory dir must not interleave."""
    from deeptutor.tutorbot.agent.memory import MemoryStore

    user_dir = tmp_path / "u" / "memory"
    store = MemoryStore(user_dir)
    order: list[str] = []

    async def fake_consolidate(label: str) -> None:
        async with _memory_lock(store.memory_dir):
            order.append(f"start-{label}")
            await asyncio.sleep(0.01)
            order.append(f"end-{label}")

    await asyncio.gather(
        fake_consolidate("a"),
        fake_consolidate("b"),
    )

    # Must see start-a, end-a, start-b, end-b (or b/a) — never interleaved.
    pairs = list(zip(order[::2], order[1::2]))
    for start, end in pairs:
        assert start.startswith("start-") and end.startswith("end-")
        assert start.removeprefix("start-") == end.removeprefix("end-")
