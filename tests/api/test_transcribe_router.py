import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers.transcribe import router
from deeptutor.services.stt import STTResult


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _audio_file(data: bytes = b"\x00\x01\x02", name: str = "voice.webm",
                content_type: str = "audio/webm"):
    return ("file", (name, io.BytesIO(data), content_type))


def test_happy_path(client):
    fake_provider = AsyncMock()
    fake_provider.transcribe = AsyncMock(
        return_value=STTResult(transcript="hello world", language="en", duration_ms=1500)
    )
    with patch("deeptutor.api.routers.transcribe.get_stt_provider", return_value=fake_provider):
        resp = client.post("/api/v1/transcribe", files=[_audio_file()])
    assert resp.status_code == 200
    body = resp.json()
    assert body["transcript"] == "hello world"
    assert body["language"] == "en"
    assert body["duration_ms"] == 1500


def test_language_hint_passed(client):
    fake_provider = AsyncMock()
    fake_provider.transcribe = AsyncMock(
        return_value=STTResult(transcript="你好", language="zh")
    )
    with patch("deeptutor.api.routers.transcribe.get_stt_provider", return_value=fake_provider):
        resp = client.post(
            "/api/v1/transcribe",
            files=[_audio_file()],
            data={"language": "zh"},
        )
    assert resp.status_code == 200
    fake_provider.transcribe.assert_awaited_once()
    kwargs = fake_provider.transcribe.await_args.kwargs
    assert kwargs["language"] == "zh"


def test_oversize_returns_413(client, monkeypatch):
    monkeypatch.setenv("STT_MAX_BYTES", "100")
    # 200 bytes payload > 100 byte cap
    resp = client.post("/api/v1/transcribe", files=[_audio_file(data=b"\x00" * 200)])
    assert resp.status_code == 413


def test_unsupported_mime_returns_415(client):
    resp = client.post(
        "/api/v1/transcribe",
        files=[_audio_file(content_type="application/octet-stream")],
    )
    assert resp.status_code == 415


def test_provider_error_returns_502(client):
    fake_provider = AsyncMock()
    fake_provider.transcribe = AsyncMock(side_effect=RuntimeError("upstream down"))
    with patch("deeptutor.api.routers.transcribe.get_stt_provider", return_value=fake_provider):
        resp = client.post("/api/v1/transcribe", files=[_audio_file()])
    assert resp.status_code == 502
