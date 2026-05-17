"""Tests for the one-shot disk migration."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def _run_migration(project_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "migrate_to_user_isolated_layout.py"),
         "--project-root", str(project_root)],
        capture_output=True, text=True,
    )


def _seed_tree(root: Path) -> None:
    (root / "data" / "memory").mkdir(parents=True)
    (root / "data" / "memory" / "PROFILE.md").write_text("old contaminated")
    (root / "data" / "tutorbot" / "foo-bot").mkdir(parents=True)
    (root / "data" / "tutorbot" / "_souls.yaml").write_text("- id: x\n")
    (root / "data" / "user" / "settings").mkdir(parents=True)
    (root / "data" / "knowledge_bases").mkdir(parents=True)


def test_migrate_creates_admin_dir_and_wipes_data(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    result = _run_migration(tmp_path)
    assert result.returncode == 0, result.stderr

    assert not (tmp_path / "data" / "memory").exists()
    assert not (tmp_path / "data" / "tutorbot").exists()
    assert (tmp_path / "multi-user" / "admin" / "memory").is_dir()
    assert (tmp_path / "multi-user" / "admin" / "tutorbot").is_dir()
    assert (tmp_path / "multi-user" / "_shared" / "knowledge_bases").is_dir()


def test_migrate_is_idempotent_refuses_overwrite(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    admin_memory = tmp_path / "multi-user" / "admin" / "memory"
    admin_memory.mkdir(parents=True)
    (admin_memory / "PROFILE.md").write_text("existing user content")

    result = _run_migration(tmp_path)
    assert result.returncode != 0
    assert "already exists" in (result.stdout + result.stderr).lower()
    assert (tmp_path / "data" / "memory").is_dir()
    assert (admin_memory / "PROFILE.md").read_text() == "existing user content"


def test_migrate_leaves_data_user_and_data_knowledge_bases_alone(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    (tmp_path / "data" / "user" / "settings" / "main.yaml").write_text("x: 1")
    (tmp_path / "data" / "knowledge_bases" / "kb1").mkdir()

    _run_migration(tmp_path)

    assert (tmp_path / "data" / "user" / "settings" / "main.yaml").read_text() == "x: 1"
    assert (tmp_path / "data" / "knowledge_bases" / "kb1").is_dir()
