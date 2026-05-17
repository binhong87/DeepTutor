"""Two-layer soul library: built-in catalog + per-user overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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


def _enter(uid: str):
    user = CurrentUser(
        id=uid, username=uid, role="user",
        scope=UserScope(kind="user", user_id=uid,
                        root=(mu_paths.MULTI_USER_ROOT / uid).resolve()),
    )
    return set_current_user(user)


def test_fresh_user_sees_only_builtins() -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token = _enter("u_alice")
    souls = get_tutorbot_manager().list_souls()
    reset_current_user(token)

    builtin_ids = {s["id"] for s in souls if s["source"] == "builtin"}
    assert {"default-tutorbot", "math-tutor", "coding-assistant"} <= builtin_ids
    assert all(not s["editable"] for s in souls if s["source"] == "builtin")
    assert not any(s["source"] == "user" for s in souls)


def test_user_override_wins_over_builtin() -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token = _enter("u_alice")
    mgr = get_tutorbot_manager()
    mgr.create_soul("math-tutor", "Custom Math Tutor", "# Soul\nMy override.")
    souls = mgr.list_souls()
    reset_current_user(token)

    math = next(s for s in souls if s["id"] == "math-tutor")
    assert math["source"] == "user"
    assert math["editable"] is True
    assert math["name"] == "Custom Math Tutor"
    assert "My override" in math["content"]


def test_delete_user_soul_reverts_to_builtin() -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token = _enter("u_alice")
    mgr = get_tutorbot_manager()
    mgr.create_soul("math-tutor", "Custom", "# Soul\nMine.")
    assert mgr.delete_soul("math-tutor") is True
    souls = mgr.list_souls()
    reset_current_user(token)

    math = next(s for s in souls if s["id"] == "math-tutor")
    assert math["source"] == "builtin"
    assert math["editable"] is False


def test_delete_builtin_only_returns_false() -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token = _enter("u_alice")
    mgr = get_tutorbot_manager()
    assert mgr.delete_soul("math-tutor") is False
    souls = mgr.list_souls()
    reset_current_user(token)

    assert any(s["id"] == "math-tutor" and s["source"] == "builtin" for s in souls)


def test_user_souls_are_per_user() -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token_a = _enter("u_alice")
    get_tutorbot_manager().create_soul("alices-soul", "A", "content")
    reset_current_user(token_a)

    token_b = _enter("u_bob")
    bob_ids = {s["id"] for s in get_tutorbot_manager().list_souls()}
    reset_current_user(token_b)

    assert "alices-soul" not in bob_ids


def test_user_souls_file_is_per_user_path(tmp_path: Path) -> None:
    from deeptutor.services.tutorbot import get_tutorbot_manager

    token = _enter("u_alice")
    mgr = get_tutorbot_manager()
    mgr.create_soul("custom", "x", "y")
    reset_current_user(token)

    expected = (tmp_path / "multi-user" / "u_alice" / "tutorbot" / "_souls.yaml").resolve()
    assert expected.is_file()
    data = yaml.safe_load(expected.read_text(encoding="utf-8"))
    assert any(s["id"] == "custom" for s in data)
