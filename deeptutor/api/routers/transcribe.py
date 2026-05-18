"""HTTP endpoint for voice-to-text transcription.

The frontend MicButton records audio via MediaRecorder and POSTs the
blob here. We hand the bytes to the configured STT provider and return
the transcript. No persistence — the audio blob lives only for the
duration of this request.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from deeptutor.services.stt import get_stt_provider

logger = logging.getLogger(__name__)

router = APIRouter()

# Keep in sync with deeptutor/services/stt/providers/openai_whisper.py's
# _MIME_TO_EXT — the router is the security boundary; the provider can
# accept anything the router lets through.
ALLOWED_AUDIO_MIMES = {
    "audio/webm",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/opus",
    "audio/flac",
    "audio/aac",
}

_DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # 25 MB


def _max_bytes() -> int:
    raw = os.environ.get("STT_MAX_BYTES", "").strip()
    if raw and raw.isdigit():
        return int(raw)
    return _DEFAULT_MAX_BYTES


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict:
    mime = (file.content_type or "").lower().split(";")[0].strip()
    if mime not in ALLOWED_AUDIO_MIMES:
        raise HTTPException(status_code=415, detail=f"Unsupported audio MIME: {mime!r}")

    audio = await file.read()
    limit = _max_bytes()
    if len(audio) > limit:
        raise HTTPException(status_code=413, detail=f"Audio exceeds {limit} byte limit")

    try:
        provider = get_stt_provider()
        result = await provider.transcribe(
            audio,
            mime_type=mime,
            # Prefer explicit hint → env default → let provider auto-detect
            language=(language or os.environ.get("STT_DEFAULT_LANGUAGE") or "").strip() or None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("STT provider failed")
        raise HTTPException(
            status_code=502,
            detail="Transcription failed: upstream provider error",
        ) from exc

    return {
        "transcript": result.transcript,
        "language": result.language,
        "duration_ms": result.duration_ms,
    }
