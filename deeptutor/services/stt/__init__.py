"""Speech-to-text service (provider-agnostic)."""

from deeptutor.services.stt.base import STTProvider, STTResult
from deeptutor.services.stt.provider_registry import (
    get_stt_provider,
    register_stt_provider,
)

__all__ = ["STTProvider", "STTResult", "get_stt_provider", "register_stt_provider"]
