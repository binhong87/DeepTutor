"""Registry for STT providers.

Providers self-register at import time (see ``providers/__init__.py``).
:func:`get_stt_provider` resolves ``STT_PROVIDER`` env var (default
``openai_whisper``) and instantiates the registered class.
"""

from __future__ import annotations

import os

from deeptutor.core.errors import ConfigurationError
from deeptutor.services.stt.base import STTProvider

_PROVIDERS: dict[str, type[STTProvider]] = {}
_DEFAULT_PROVIDER = "openai_whisper"


def register_stt_provider(name: str, cls: type[STTProvider]) -> None:
    """Register *cls* under *name*. Idempotent — last registration wins."""
    _PROVIDERS[name.lower()] = cls


def get_stt_provider() -> STTProvider:
    """Return an instance of the configured STT provider."""
    name = (os.environ.get("STT_PROVIDER") or _DEFAULT_PROVIDER).lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ConfigurationError(
            f"Unknown STT provider {name!r}. Available: {sorted(_PROVIDERS)}"
        )
    return cls()
