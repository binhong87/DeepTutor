"""Tests for audio input capability support."""

import pytest

from deeptutor.services.llm.capabilities import supports_audio


@pytest.mark.parametrize(
    "binding,model,expected",
    [
        ("openai", "gpt-4o-audio-preview", True),
        ("openai", "gpt-4o-audio-preview-2026-01-15", True),  # version-suffixed
        ("openai", "gpt-4o-mini-audio-preview", True),
        ("openai", "gpt-4o", False),                          # vision only, no audio
        ("openai", "gpt-3.5-turbo", False),
        ("gemini", "gemini-2.0-flash", True),
        ("gemini", "gemini-2.5-pro", True),
        ("gemini", "gemini-1.5-pro", False),                  # older version
        ("anthropic", "claude-opus-4-7", False),              # no audio support
        ("OpenAI", "gpt-4o-audio-preview", True),             # case-insensitive binding
        ("openai", None, False),
        ("", "gpt-4o-audio-preview", False),                  # blank binding
        ("ollama", "llama3", False),                          # unknown binding
    ],
)
def test_supports_audio_matrix(binding, model, expected):
    """Test audio support across various provider/model combinations."""
    assert supports_audio(binding, model) is expected
