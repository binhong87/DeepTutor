"""STT provider implementations.

Each submodule self-registers via :func:`register_stt_provider`. Importing
this package triggers registration of every shipped provider.
"""

from deeptutor.services.stt.providers import openai_whisper  # noqa: F401  (side-effect)
