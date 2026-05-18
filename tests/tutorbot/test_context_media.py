"""Tests for ContextBuilder.build_user_message_with_media."""

import base64
from pathlib import Path

import pytest

from deeptutor.core.context import Attachment
from deeptutor.tutorbot.agent.context import ContextBuilder


@pytest.fixture
def builder(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_memory = tmp_path / "memory"
    user_memory.mkdir()
    return ContextBuilder(workspace=workspace, user_memory_dir=user_memory)


def test_no_attachments_returns_plain_text(builder):
    result = builder.build_user_message_with_media(
        text="hello", attachments=[], binding="openai", model="gpt-4o-audio-preview",
    )
    assert result == "hello"


def test_image_attachment_produces_multimodal_array(builder):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    att = Attachment(
        type="image",
        base64=base64.b64encode(png_bytes).decode(),
        mime_type="image/png",
        filename="x.png",
    )
    result = builder.build_user_message_with_media(
        text="describe",
        attachments=[att],
        binding="openai",
        model="gpt-4o",  # vision-capable
    )
    assert isinstance(result, list)
    assert any(p.get("type") == "text" and p.get("text") == "describe" for p in result)
    assert any(p.get("type") == "image_url" for p in result)


def test_audio_injected_for_audio_capable_model(builder):
    att = Attachment(
        type="audio",
        base64="ZmFrZQ==",
        mime_type="audio/webm",
        filename="voice.webm",
    )
    result = builder.build_user_message_with_media(
        text="what did I say",
        attachments=[att],
        binding="openai",
        model="gpt-4o-audio-preview",
    )
    assert isinstance(result, list)
    assert any(p.get("type") == "text" and p.get("text") == "what did I say" for p in result)
    assert any(p.get("type") == "input_audio" for p in result)


def test_audio_dropped_for_non_audio_model(builder):
    att = Attachment(type="audio", base64="ZmFrZQ==", mime_type="audio/webm")
    result = builder.build_user_message_with_media(
        text="what did I say",
        attachments=[att],
        binding="openai",
        model="gpt-4o",  # vision but no audio
    )
    # No audio part injected; text preserved (string OR text-only list both acceptable)
    if isinstance(result, list):
        assert not any(p.get("type") == "input_audio" for p in result)
        assert any(p.get("type") == "text" for p in result)
    else:
        assert result == "what did I say"


def test_path_based_callers_unaffected(builder, tmp_path):
    """The original _build_user_content(text, media: list[str]) path still works
    so existing tutorbot callers that pass file paths are not broken."""
    img_path = tmp_path / "y.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    result = builder._build_user_content(text="see this", media=[str(img_path)])
    assert isinstance(result, list)
    assert any(p.get("type") == "image_url" for p in result)
