"""Tests for audio attachment handling in multimodal message preparation."""

from dataclasses import dataclass

from deeptutor.services.llm.multimodal import prepare_multimodal_messages


@dataclass
class _Attachment:
    type: str
    base64: str = ""
    mime_type: str = ""
    filename: str = ""
    url: str = ""


def _msgs():
    return [{"role": "user", "content": "What did I say?"}]


def test_audio_injected_for_supported_model():
    audio = _Attachment(type="audio", base64="ZmFrZQ==", mime_type="audio/webm",
                        filename="voice.webm")
    result = prepare_multimodal_messages(
        _msgs(), [audio], binding="openai", model="gpt-4o-audio-preview",
    )
    content = result.messages[0]["content"]
    assert isinstance(content, list)
    # Text part still present
    assert any(p.get("type") == "text" and p.get("text") == "What did I say?" for p in content)
    # Audio part present
    audio_parts = [p for p in content if p.get("type") == "input_audio"]
    assert len(audio_parts) == 1
    assert audio_parts[0]["input_audio"]["data"] == "ZmFrZQ=="
    assert audio_parts[0]["input_audio"]["format"] == "webm"
    assert result.audio_dropped == 0


def test_audio_silently_dropped_for_unsupported_model():
    audio = _Attachment(type="audio", base64="ZmFrZQ==", mime_type="audio/webm")
    result = prepare_multimodal_messages(
        _msgs(), [audio], binding="openai", model="gpt-4o",
    )
    # Message unchanged — no audio part, text content preserved
    msg = result.messages[0]
    assert msg["content"] == "What did I say?" or msg["content"] == [
        {"type": "text", "text": "What did I say?"}
    ]
    assert result.audio_dropped == 0  # Not "dropped" — never injected; transcript is fallback


def test_audio_and_image_coexist():
    audio = _Attachment(type="audio", base64="QQ==", mime_type="audio/webm")
    image = _Attachment(type="image", base64="Qg==", mime_type="image/png", filename="x.png")
    result = prepare_multimodal_messages(
        _msgs(), [audio, image], binding="openai", model="gpt-4o-audio-preview",
    )
    content = result.messages[0]["content"]
    types = [p.get("type") for p in content]
    assert "input_audio" in types
    assert "image_url" in types
    assert "text" in types


def test_audio_mime_to_format_mapping():
    cases = [
        ("audio/webm", "webm"),
        ("audio/mp4", "mp4"),
        ("audio/wav", "wav"),
        ("audio/mpeg", "mp3"),
    ]
    for mime, expected_format in cases:
        audio = _Attachment(type="audio", base64="QQ==", mime_type=mime)
        result = prepare_multimodal_messages(
            _msgs(), [audio], binding="openai", model="gpt-4o-audio-preview",
        )
        part = next(p for p in result.messages[0]["content"] if p.get("type") == "input_audio")
        assert part["input_audio"]["format"] == expected_format, mime


def test_no_audio_no_change():
    msgs = [{"role": "user", "content": "hi"}]
    result = prepare_multimodal_messages(msgs, [], binding="openai", model="gpt-4o-audio-preview")
    assert result.messages[0]["content"] == "hi"
    assert result.audio_dropped == 0


def test_audio_url_resolved_to_base64_for_supported_model(tmp_path, monkeypatch):
    """An audio attachment with only `url` (post-persist) should still be
    injected for audio-capable models — _inject_audio must resolve the
    URL → bytes the same way _inject_images does."""
    import base64

    from deeptutor.services.llm.multimodal import prepare_multimodal_messages

    # Set up a fake on-disk file the store can resolve
    sid, aid, fname = "sid_abc", "aid_xyz", "voice.webm"
    audio_dir = tmp_path / "attachments" / sid
    audio_dir.mkdir(parents=True)
    audio_bytes = b"\x1aE\xdf\xa3"  # WebM/Matroska magic header (truncated)
    (audio_dir / f"{aid}_{fname}").write_bytes(audio_bytes)
    monkeypatch.setenv("CHAT_ATTACHMENT_DIR", str(tmp_path / "attachments"))

    # Reset the AttachmentStore singleton so it picks up the new env
    from deeptutor.services.storage.attachment_store import reset_attachment_store
    reset_attachment_store()

    att = _Attachment(type="audio", url=f"/api/attachments/{sid}/{aid}/{fname}", mime_type="audio/webm")
    msgs = [{"role": "user", "content": "what did I say"}]

    result = prepare_multimodal_messages(
        msgs, [att], binding="openai", model="gpt-4o-audio-preview",
    )
    content = result.messages[0]["content"]
    assert isinstance(content, list)
    audio_parts = [p for p in content if p.get("type") == "input_audio"]
    assert len(audio_parts) == 1, f"audio not injected: {content}"
    # Round-trip: the data field should be base64 of the original bytes
    assert audio_parts[0]["input_audio"]["data"] == base64.b64encode(audio_bytes).decode()
    assert audio_parts[0]["input_audio"]["format"] == "webm"
    # No drop reported — the URL resolved successfully
    assert getattr(result, "audio_dropped", 0) == 0
