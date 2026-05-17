"""Shared knowledge-base plumbing — prefix parsing and path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.multi_user import paths as mu_paths
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    multi_user_root = tmp_path / "multi-user"
    shared_root = multi_user_root / "_shared"
    monkeypatch.setattr(mu_paths, "MULTI_USER_ROOT", multi_user_root)
    monkeypatch.setattr(mu_paths, "SHARED_ROOT", shared_root)
    monkeypatch.setattr(mu_paths, "_path_services", {})


def _enter(uid: str, *, role: str = "user") -> object:
    scope = UserScope(
        kind="user",
        user_id=uid,
        root=(mu_paths.MULTI_USER_ROOT / uid).resolve(),
    )
    user = CurrentUser(id=uid, username=uid, role=role, scope=scope)  # type: ignore[arg-type]
    return set_current_user(user)


def test_shared_path_service_resolves_under_shared(tmp_path: Path) -> None:
    from deeptutor.multi_user.paths import get_shared_path_service

    svc = get_shared_path_service()
    kb_root = svc.get_knowledge_bases_root()
    assert "_shared" in kb_root.parts
    assert kb_root.name == "knowledge_bases"


def test_current_path_service_never_resolves_to_shared(tmp_path: Path) -> None:
    from deeptutor.multi_user.paths import get_path_service_for_scope

    scope = UserScope(
        kind="user",
        user_id="u_alice",
        root=(mu_paths.MULTI_USER_ROOT / "u_alice").resolve(),
    )
    (scope.root / "knowledge_bases").mkdir(parents=True, exist_ok=True)
    svc = get_path_service_for_scope(scope)
    kb_root = svc.get_knowledge_bases_root()
    assert "_shared" not in kb_root.parts


def test_resolve_kb_with_shared_prefix(tmp_path: Path) -> None:
    from deeptutor.multi_user.knowledge_access import resolve_kb

    token = _enter("u_alice")
    try:
        resource = resolve_kb("shared:kb:physics-101")
    finally:
        reset_current_user(token)

    assert resource.source == "shared"
    assert resource.read_only is True
    assert resource.id == "shared:kb:physics-101"
    assert resource.name == "physics-101"
    assert "_shared" in resource.base_dir.parts
