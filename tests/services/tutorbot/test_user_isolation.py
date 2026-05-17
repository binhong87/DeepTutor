"""Cross-user isolation tests for TutorBotManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.multi_user import paths as mu_paths
from deeptutor.multi_user.context import set_current_user, reset_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mu_paths, "MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(mu_paths, "SHARED_ROOT", tmp_path / "multi-user" / "_shared")
    monkeypatch.setattr(mu_paths, "SYSTEM_ROOT", tmp_path / "multi-user" / "_system")
    mu_paths._path_services.clear()

    from deeptutor.services.tutorbot import manager as mgr_mod
    mgr_mod._managers.clear()


def _make_user(uid: str) -> CurrentUser:
    return CurrentUser(
        id=uid,
        username=uid,
        role="user",
        scope=UserScope(kind="user", user_id=uid,
                        root=(mu_paths.MULTI_USER_ROOT / uid).resolve()),
    )


def test_managers_are_distinct_per_user() -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token_a = set_current_user(_make_user("u_alice"))
    mgr_a = get_tutorbot_manager()
    reset_current_user(token_a)

    token_b = set_current_user(_make_user("u_bob"))
    mgr_b = get_tutorbot_manager()
    reset_current_user(token_b)

    assert mgr_a is not mgr_b
    assert mgr_a._scope.user_id == "u_alice"
    assert mgr_b._scope.user_id == "u_bob"


def test_two_users_get_disjoint_memory_dirs(tmp_path: Path) -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token_a = set_current_user(_make_user("u_alice"))
    mem_a = get_tutorbot_manager()._memory_dir
    reset_current_user(token_a)

    token_b = set_current_user(_make_user("u_bob"))
    mem_b = get_tutorbot_manager()._memory_dir
    reset_current_user(token_b)

    assert mem_a == (tmp_path / "multi-user" / "u_alice" / "memory").resolve()
    assert mem_b == (tmp_path / "multi-user" / "u_bob" / "memory").resolve()
    assert mem_a != mem_b


def test_no_path_resolves_under_data_dir(tmp_path: Path) -> None:
    """The manager must never produce a path under project_root/'data'."""
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token = set_current_user(_make_user("u_alice"))
    mgr = get_tutorbot_manager()
    reset_current_user(token)

    for path in (mgr._memory_dir, mgr._tutorbot_dir, mgr._user_souls_file):
        assert "data" not in path.parts or path.is_relative_to(tmp_path / "multi-user")


def test_admin_workspace_is_under_multi_user(tmp_path: Path) -> None:
    from deeptutor.multi_user.paths import local_admin_user

    user = local_admin_user()
    assert user.scope.root == (tmp_path / "multi-user" / "admin").resolve()
