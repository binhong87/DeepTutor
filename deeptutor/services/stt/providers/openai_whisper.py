"""OpenAI Whisper STT provider.

Reuses the ``openai`` SDK that's already a top-level dep. Supports
OpenAI-compatible local servers (LM Studio, faster-whisper-server, Groq
Whisper) via the standard ``base_url`` override — falls back to
``LLM_HOST`` so users with a local LLM endpoint get STT for free.
"""

from __future__ import annotations

import io
import os
from typing import Any

from openai import AsyncOpenAI

from deeptutor.core.errors import ConfigurationError
from deeptutor.services.stt.base import STTResult
from deeptutor.services.stt.provider_registry import register_stt_provider

_MIME_TO_EXT = {
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
    "audio/aac": ".aac",
}


class OpenAIWhisperProvider:
    name = "openai_whisper"

    def __init__(self) -> None:
        api_key = os.environ.get("STT_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "STT_API_KEY not set (and LLM_API_KEY unavailable as fallback)"
            )
        base_url = os.environ.get("STT_HOST") or os.environ.get("LLM_HOST") or None
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = os.environ.get("STT_MODEL") or "whisper-1"

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime_type: str,
        language: str | None = None,
    ) -> STTResult:
        ext = _MIME_TO_EXT.get(mime_type.lower(), ".bin")
        buf = io.BytesIO(audio)
        buf.name = f"audio{ext}"  # OpenAI SDK reads .name to pick decoder

        resp = await self._client.audio.transcriptions.create(
            file=buf,
            model=self._model,
            language=language or None,
            response_format="verbose_json",
        )

        text = getattr(resp, "text", "") or ""
        lang = getattr(resp, "language", None)
        duration = getattr(resp, "duration", 0.0) or 0.0
        duration_ms = int(duration * 1000) or None
        raw = resp.model_dump() if hasattr(resp, "model_dump") else None

        return STTResult(
            transcript=text,
            language=lang,
            duration_ms=duration_ms,
            raw=raw,
        )


register_stt_provider("openai_whisper", OpenAIWhisperProvider)
