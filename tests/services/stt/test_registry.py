import os
from unittest.mock import patch

import pytest

from deeptutor.core.errors import ConfigurationError
from deeptutor.services.stt import STTResult, get_stt_provider, register_stt_provider
from deeptutor.services.stt.provider_registry import _PROVIDERS


class _FakeProvider:
    name = "fake"

    async def transcribe(self, audio, *, mime_type, language=None):
        return STTResult(transcript="ok")


@pytest.fixture(autouse=True)
def _clear_registry():
    snapshot = dict(_PROVIDERS)
    yield
    _PROVIDERS.clear()
    _PROVIDERS.update(snapshot)


def test_register_and_get_round_trip():
    register_stt_provider("fake", _FakeProvider)
    with patch.dict(os.environ, {"STT_PROVIDER": "fake"}):
        provider = get_stt_provider()
    assert isinstance(provider, _FakeProvider)


def test_unknown_provider_raises_configuration_error():
    with patch.dict(os.environ, {"STT_PROVIDER": "does_not_exist"}, clear=False):
        with pytest.raises(ConfigurationError) as exc_info:
            get_stt_provider()
    assert "does_not_exist" in str(exc_info.value)


def test_default_provider_is_openai_whisper():
    # Default selection used when env unset
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("STT_PROVIDER", None)
        register_stt_provider("openai_whisper", _FakeProvider)
        provider = get_stt_provider()
    assert provider.name == "fake"  # _FakeProvider registered under the default key
