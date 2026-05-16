"""Tests for the per-user scope refactor."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.multi_user import paths as mu_paths
from deeptutor.multi_user.models import LOCAL_ADMIN_ID


@pytest.fixture(autouse=True)
def _isolate_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mu_paths, "MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(mu_paths, "SHARED_ROOT", tmp_path / "multi-user" / "_shared")
    monkeypatch.setattr(mu_paths, "SYSTEM_ROOT", tmp_path / "multi-user" / "_system")
    mu_paths._path_services.clear()


def test_admin_scope_lives_under_multi_user(tmp_path: Path) -> None:
    scope = mu_paths.admin_scope()
    assert scope.user_id == LOCAL_ADMIN_ID
    assert scope.root == (tmp_path / "multi-user" / LOCAL_ADMIN_ID).resolve()


def test_scope_for_user_ignores_is_admin_for_paths(tmp_path: Path) -> None:
    a = mu_paths.scope_for_user("u_alice", is_admin=False)
    b = mu_paths.scope_for_user("u_alice", is_admin=True)
    assert a.root == b.root == (tmp_path / "multi-user" / "u_alice").resolve()


def test_admin_workspace_root_constant_removed() -> None:
    assert not hasattr(mu_paths, "ADMIN_WORKSPACE_ROOT")


def test_get_shared_path_service_resolves_under_shared(tmp_path: Path) -> None:
    svc = mu_paths.get_shared_path_service()
    assert svc.workspace_root == (tmp_path / "multi-user" / "_shared").resolve()


def test_local_admin_id_is_admin_literal() -> None:
    assert LOCAL_ADMIN_ID == "admin"
