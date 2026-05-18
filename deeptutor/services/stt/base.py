"""STT provider Protocol and result dataclass.

Voice transcription runs server-side via a provider plugin. Adding a new
provider means writing one file under ``providers/`` and self-registering
with :func:`register_stt_provider` — same pattern as ``services/search/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class STTResult:
    """Result of a single transcription call.

    Attributes:
        transcript: Recognised text. May be empty for silent or noise-only audio.
        language: ISO 639-1 code if the provider detected/returned one.
        duration_ms: Audio duration in milliseconds (if known).
        raw: Provider-native response payload — kept for debugging only.
    """

    transcript: str
    language: str | None = None
    duration_ms: int | None = None
    raw: dict[str, Any] | None = None


@runtime_checkable
class STTProvider(Protocol):
    """Protocol every STT provider must implement."""

    name: str

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime_type: str,
        language: str | None = None,
    ) -> STTResult:
        """Transcribe audio bytes and return the recognised text.

        Args:
            audio: Raw audio bytes to transcribe.
            mime_type: MIME type of the audio (e.g. ``"audio/webm"``, ``"audio/wav"``).
            language: Optional ISO 639-1 language hint (e.g. ``"en"``, ``"zh"``).
                The provider may auto-detect if not specified.

        Returns:
            An :class:`STTResult` containing the transcript, detected language,
            and provider-specific metadata.
        """
