"""Tests for the history endpoint's attachment enrichment.

The bulk of the logic is in the pure helper `_extract_attachments_and_clean_content`,
which is unit-testable in isolation. A single integration test then exercises
the full ``get_bot_history`` path with a temp JSONL via _bot_workspace patching.
"""

from __future__ import annotations

from typing import Any


# ── Unit tests for the helper ───────────────────────────────────────────────


def test_helper_extracts_image_url_and_strips_image_text():
    from deeptutor.services.tutorbot.manager import _extract_attachments_and_clean_content

    content = [
        {"type": "text", "text": "describe this"},
        {"type": "image_url",
         "image_url": {"url": "/api/attachments/sid/aid/picture.png"}},
    ]
    text, attachments = _extract_attachments_and_clean_content(content)
    assert "describe this" in text
    assert "[image]" not in text
    assert attachments == [
        {
            "type": "image",
            "url": "/api/attachments/sid/aid/picture.png",
            "mime_type": "image/png",
            "filename": "picture.png",
        }
    ]


def test_helper_text_only_content_returns_none_attachments():
    from deeptutor.services.tutorbot.manager import _extract_attachments_and_clean_content

    text, attachments = _extract_attachments_and_clean_content("just plain text")
    assert text == "just plain text"
    assert attachments is None


def test_helper_data_scheme_image_url_ignored():
    """Defensive: legacy data: URLs do NOT become attachment entries —
    only /api/attachments/ URLs qualify. Falls through to the existing
    normalize_message_content path, which renders them as [image]."""
    from deeptutor.services.tutorbot.manager import _extract_attachments_and_clean_content

    content = [
        {"type": "text", "text": "old turn"},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}},
    ]
    text, attachments = _extract_attachments_and_clean_content(content)
    assert attachments is None
    assert "old turn" in text
    assert "[image]" in text  # the data: URL part renders as [image]


def test_helper_handles_non_list_content():
    """Content can arrive as plain string (text-only turn) — no crash,
    no attachments, text returned through normalize."""
    from deeptutor.services.tutorbot.manager import _extract_attachments_and_clean_content

    text, attachments = _extract_attachments_and_clean_content(None)
    assert text == ""
    assert attachments is None


def test_helper_rehydrates_legacy_placeholder_text_into_attachment():
    """Legacy turns may carry a text part like
    ``[image: /api/attachments/<sid>/<aid>/<name>]`` left behind by the
    strip-image-retry path. The history endpoint should re-emit those as
    attachments so the bubble still renders the image."""
    from deeptutor.services.tutorbot.manager import _extract_attachments_and_clean_content

    content = [
        {"type": "text", "text": "Please look"},
        {"type": "text",
         "text": "[image: /api/attachments/sid/aid/picture.png]"},
    ]
    text, attachments = _extract_attachments_and_clean_content(content)
    assert "Please look" in text
    assert "[image:" not in text  # placeholder consumed
    assert attachments == [
        {
            "type": "image",
            "url": "/api/attachments/sid/aid/picture.png",
            "mime_type": "image/png",
            "filename": "picture.png",
        }
    ]


def test_helper_recovers_placeholder_when_text_has_extra_content():
    """The placeholder may share its text part with adjacent text — the
    helper extracts the image and keeps the leftover text."""
    from deeptutor.services.tutorbot.manager import _extract_attachments_and_clean_content

    content = [
        {"type": "text", "text": "before [image: /api/attachments/s/a/x.png] after"},
    ]
    text, attachments = _extract_attachments_and_clean_content(content)
    assert attachments and attachments[0]["url"] == "/api/attachments/s/a/x.png"
    assert "before" in text
    assert "after" in text
    assert "[image:" not in text


# ── Integration test through get_bot_history ─────────────────────────────────


def test_get_bot_history_emits_attachments_field(tmp_path, monkeypatch):
    """End-to-end: write a JSONL with an image_url URL part, call
    get_bot_history, verify the user entry has top-level attachments and
    that [image] noise is gone from content."""
    import json
    from deeptutor.services.tutorbot.manager import get_tutorbot_manager

    bot_id = "phase2-test-bot"
    session_id = "s_abc"

    # Patch the manager's _bot_workspace to point at tmp_path so we don't
    # touch real data/tutorbot/.
    workspace = tmp_path / "ws"
    sessions_dir = workspace / "sessions"
    sessions_dir.mkdir(parents=True)
    jsonl = sessions_dir / f"bot_{bot_id}_s_{session_id}.jsonl"
    jsonl.write_text(
        json.dumps({
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image_url",
                 "image_url": {"url": f"/api/attachments/{session_id}/aid/picture.png"}},
            ],
            "timestamp": "2026-05-18T10:00:00Z",
        }) + "\n" +
        json.dumps({
            "role": "assistant",
            "content": "It looks like a picture.",
            "timestamp": "2026-05-18T10:00:01Z",
        }) + "\n",
        encoding="utf-8",
    )

    mgr = get_tutorbot_manager()
    monkeypatch.setattr(mgr, "_bot_workspace", lambda bid: workspace)

    history = mgr.get_bot_history(bot_id, session_id=session_id, limit=10)
    assert len(history) == 2
    user_entry = next(h for h in history if h["role"] == "user")
    assert "describe this" in user_entry["content"]
    assert "[image]" not in user_entry["content"]
    assert user_entry.get("attachments") == [
        {
            "type": "image",
            "url": f"/api/attachments/{session_id}/aid/picture.png",
            "mime_type": "image/png",
            "filename": "picture.png",
        }
    ]
    # Assistant entry untouched
    assistant_entry = next(h for h in history if h["role"] == "assistant")
    assert assistant_entry["content"] == "It looks like a picture."
    assert "attachments" not in assistant_entry
