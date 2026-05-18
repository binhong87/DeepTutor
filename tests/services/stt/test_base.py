from dataclasses import fields

from deeptutor.services.stt import STTProvider, STTResult


def test_stt_result_has_required_fields():
    names = {f.name for f in fields(STTResult)}
    assert names == {"transcript", "language", "duration_ms", "raw"}


def test_stt_result_defaults():
    r = STTResult(transcript="hi")
    assert r.transcript == "hi"
    assert r.language is None
    assert r.duration_ms is None
    assert r.raw is None


def test_stt_provider_is_runtime_checkable_protocol():
    class Dummy:
        name = "dummy"

        async def transcribe(self, audio, *, mime_type, language=None):
            return STTResult(transcript="")

    assert isinstance(Dummy(), STTProvider)
