"""Unit tests for the simplified MemoryStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.tutorbot.agent.memory import MemoryStore


def test_memory_store_uses_user_memory_dir_directly(tmp_path: Path) -> None:
    user_dir = tmp_path / "u_alice" / "memory"
    store = MemoryStore(user_dir)

    assert store.memory_dir == user_dir
    assert store.memory_file == user_dir / "PROFILE.md"
    assert store.history_file == user_dir / "SUMMARY.md"


def test_memory_store_creates_dir_on_init(tmp_path: Path) -> None:
    user_dir = tmp_path / "u_bob" / "memory"
    assert not user_dir.exists()
    MemoryStore(user_dir)
    assert user_dir.is_dir()


def test_memory_store_writes_and_reads_long_term(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "u" / "memory")
    store.write_long_term("hello")
    assert "hello" in store.read_long_term()


def test_memory_store_init_rejects_no_path() -> None:
    with pytest.raises(TypeError):
        MemoryStore()  # type: ignore[call-arg]


def test_first_write_to_empty_profile_gets_user_stamp(tmp_path: Path) -> None:
    user_dir = tmp_path / "u_alice" / "memory"
    store = MemoryStore(user_dir)

    store.write_long_term("## Identity\n- Likes geometry\n")
    content = store.read_long_term()

    assert content.startswith("> User: u_alice")
    assert "private to this user" in content
    assert "## Identity\n- Likes geometry" in content


def test_existing_profile_with_stamp_is_not_double_stamped(tmp_path: Path) -> None:
    user_dir = tmp_path / "u_alice" / "memory"
    store = MemoryStore(user_dir)
    store.write_long_term("first content")
    store.write_long_term("second content")

    content = store.read_long_term()
    assert content.count("> User: u_alice") == 1
    assert "second content" in content
