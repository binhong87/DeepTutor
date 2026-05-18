import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("STT_API_KEY", "STT_HOST", "STT_MODEL", "LLM_API_KEY", "LLM_HOST"):
        monkeypatch.delenv(key, raising=False)
    yield


def _patch_openai():
    """Return a context manager + AsyncMock representing AsyncOpenAI."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock()

    fake_async_openai = MagicMock(return_value=mock_client)
    return patch(
        "deeptutor.services.stt.providers.openai_whisper.AsyncOpenAI",
        fake_async_openai,
    ), mock_client, fake_async_openai


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch):
    from deeptutor.core.errors import ConfigurationError
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    with pytest.raises(ConfigurationError):
        OpenAIWhisperProvider()


@pytest.mark.asyncio
async def test_falls_back_to_llm_api_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-fallback")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, _client, fake_ctor = _patch_openai()
    with patcher:
        OpenAIWhisperProvider()
        call_kwargs = fake_ctor.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-fallback"


@pytest.mark.asyncio
async def test_uses_stt_host_over_llm_host(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "sk-test")
    monkeypatch.setenv("STT_HOST", "https://stt.example")
    monkeypatch.setenv("LLM_HOST", "https://llm.example")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, _client, fake_ctor = _patch_openai()
    with patcher:
        OpenAIWhisperProvider()
        assert fake_ctor.call_args.kwargs["base_url"] == "https://stt.example"


@pytest.mark.asyncio
async def test_transcribe_maps_mime_to_extension(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "sk-test")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, mock_client, _ = _patch_openai()
    fake_resp = MagicMock(text="hello", language="en", duration=1.5)
    fake_resp.model_dump = lambda: {"text": "hello"}
    mock_client.audio.transcriptions.create.return_value = fake_resp

    with patcher:
        provider = OpenAIWhisperProvider()
        result = await provider.transcribe(b"\x00\x01", mime_type="audio/webm")

    assert result.transcript == "hello"
    assert result.language == "en"
    assert result.duration_ms == 1500
    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["file"].name.endswith(".webm")
    assert call_kwargs["model"] == "whisper-1"
    assert call_kwargs["response_format"] == "verbose_json"


@pytest.mark.asyncio
async def test_transcribe_passes_language_hint(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "sk-test")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, mock_client, _ = _patch_openai()
    fake_resp = MagicMock(text="", language="zh", duration=0.0)
    fake_resp.model_dump = lambda: {}
    mock_client.audio.transcriptions.create.return_value = fake_resp

    with patcher:
        provider = OpenAIWhisperProvider()
        await provider.transcribe(b"\x00", mime_type="audio/mp4", language="zh")

    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["language"] == "zh"
    assert call_kwargs["file"].name.endswith(".m4a")
