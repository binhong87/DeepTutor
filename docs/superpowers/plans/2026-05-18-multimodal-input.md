# Multi-Modal Input (Images + Voice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add image-attachment and voice (STT) input to the `tutorbot-web/` composer. When the active LLM supports native audio, the raw audio is forwarded alongside the transcript.

**Architecture:** Frontend Composer (extracted from BotChatView) handles image picker + paste + drag-drop + mic recording. Voice uses a new server-side STT pipeline (`services/stt/` package, OpenAI Whisper provider, `POST /api/v1/transcribe`). Both image and audio attachments travel inline as base64 in WS frames and are encoded into the LLM call by an extended `services/llm/multimodal.py`. TutorBot's `context.py` is refactored to delegate to the shared multimodal layer.

**Tech Stack:** Python 3.11+ / FastAPI / pytest / pytest-asyncio; Next.js 16 (pre-release) / React 19 / TypeScript; openai SDK (already a dep); browser `MediaRecorder` + `getUserMedia`.

**Source spec:** `docs/superpowers/specs/2026-05-18-multimodal-input-design.md` (commit `6b46c54`). All decisions in the spec's Decisions table are binding.

**Branch:** chatV2 (currently checked out). Per `CONTRIBUTING.md` and `CLAUDE.md`, work targets `dev` for the eventual PR — but commits land on this branch.

**Frontend test caveat:** `tutorbot-web/` has no test runner today (see `tutorbot-web/package.json` — only `dev`/`build`/`start`/`lint`). Frontend tasks substitute a **manual smoke step** for the automated test step. Per `tutorbot-web/AGENTS.md`, always consult `tutorbot-web/node_modules/next/dist/docs/` before writing Next.js-specific code.

---

## Phase 1 — Backend foundation (no UI changes; each task fully testable)

### Task 1: Create `services/stt/` package skeleton with Protocol and dataclass

**Files:**
- Create: `deeptutor/services/stt/__init__.py`
- Create: `deeptutor/services/stt/base.py`
- Create: `tests/services/stt/__init__.py`
- Create: `tests/services/stt/test_base.py`

- [ ] **Step 1: Write the failing test**

`tests/services/stt/test_base.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/services/stt/test_base.py`
Expected: FAIL — module `deeptutor.services.stt` does not exist.

- [ ] **Step 3: Implement `base.py`**

`deeptutor/services/stt/base.py`:
```python
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
    ) -> STTResult: ...
```

`deeptutor/services/stt/__init__.py`:
```python
"""Speech-to-text service (provider-agnostic)."""

from deeptutor.services.stt.base import STTProvider, STTResult

__all__ = ["STTProvider", "STTResult"]
```

`tests/services/stt/__init__.py`: empty file.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/services/stt/test_base.py`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add deeptutor/services/stt/__init__.py deeptutor/services/stt/base.py tests/services/stt/__init__.py tests/services/stt/test_base.py
git commit -m "feat(stt): add STTProvider Protocol and STTResult dataclass"
```

---

### Task 2: Provider registry with env-driven selection

**Files:**
- Create: `deeptutor/services/stt/provider_registry.py`
- Modify: `deeptutor/services/stt/__init__.py`
- Create: `tests/services/stt/test_registry.py`

- [ ] **Step 1: Write the failing test**

`tests/services/stt/test_registry.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/services/stt/test_registry.py`
Expected: FAIL — `register_stt_provider` / `get_stt_provider` / `provider_registry` not importable.

- [ ] **Step 3: Implement registry**

`deeptutor/services/stt/provider_registry.py`:
```python
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
```

Replace `deeptutor/services/stt/__init__.py`:
```python
"""Speech-to-text service (provider-agnostic)."""

from deeptutor.services.stt.base import STTProvider, STTResult
from deeptutor.services.stt.provider_registry import (
    get_stt_provider,
    register_stt_provider,
)

__all__ = ["STTProvider", "STTResult", "get_stt_provider", "register_stt_provider"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/services/stt/test_registry.py`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add deeptutor/services/stt/provider_registry.py deeptutor/services/stt/__init__.py tests/services/stt/test_registry.py
git commit -m "feat(stt): provider registry with env-driven selection"
```

---

### Task 3: OpenAI Whisper provider implementation

**Files:**
- Create: `deeptutor/services/stt/providers/__init__.py`
- Create: `deeptutor/services/stt/providers/openai_whisper.py`
- Create: `tests/services/stt/test_openai_whisper_provider.py`

- [ ] **Step 1: Write the failing test**

`tests/services/stt/test_openai_whisper_provider.py`:
```python
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("STT_API_KEY", "STT_HOST", "STT_MODEL", "LLM_API_KEY", "LLM_HOST"):
        monkeypatch.delenv(key, raising=False)
    yield


def _patch_openai():
    """Return a context manager + AsyncMock representing AsyncOpenAI."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock()

    fake_async_openai = MagicMock(return_value=mock_client)
    return patch(
        "deeptutor.services.stt.providers.openai_whisper.AsyncOpenAI",
        fake_async_openai,
    ), mock_client, fake_async_openai


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch):
    from deeptutor.core.errors import ConfigurationError
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    with pytest.raises(ConfigurationError):
        OpenAIWhisperProvider()


@pytest.mark.asyncio
async def test_falls_back_to_llm_api_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-fallback")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, _client, fake_ctor = _patch_openai()
    with patcher:
        OpenAIWhisperProvider()
        call_kwargs = fake_ctor.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-fallback"


@pytest.mark.asyncio
async def test_uses_stt_host_over_llm_host(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "sk-test")
    monkeypatch.setenv("STT_HOST", "https://stt.example")
    monkeypatch.setenv("LLM_HOST", "https://llm.example")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, _client, fake_ctor = _patch_openai()
    with patcher:
        OpenAIWhisperProvider()
        assert fake_ctor.call_args.kwargs["base_url"] == "https://stt.example"


@pytest.mark.asyncio
async def test_transcribe_maps_mime_to_extension(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "sk-test")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, mock_client, _ = _patch_openai()
    fake_resp = MagicMock(text="hello", language="en", duration=1.5)
    fake_resp.model_dump = lambda: {"text": "hello"}
    mock_client.audio.transcriptions.create.return_value = fake_resp

    with patcher:
        provider = OpenAIWhisperProvider()
        result = await provider.transcribe(b"\x00\x01", mime_type="audio/webm")

    assert result.transcript == "hello"
    assert result.language == "en"
    assert result.duration_ms == 1500
    # Check the BytesIO passed to .create had a .webm filename
    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["file"].name.endswith(".webm")
    assert call_kwargs["model"] == "whisper-1"
    assert call_kwargs["response_format"] == "verbose_json"


@pytest.mark.asyncio
async def test_transcribe_passes_language_hint(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "sk-test")
    from deeptutor.services.stt.providers.openai_whisper import OpenAIWhisperProvider

    patcher, mock_client, _ = _patch_openai()
    fake_resp = MagicMock(text="", language="zh", duration=0.0)
    fake_resp.model_dump = lambda: {}
    mock_client.audio.transcriptions.create.return_value = fake_resp

    with patcher:
        provider = OpenAIWhisperProvider()
        await provider.transcribe(b"\x00", mime_type="audio/mp4", language="zh")

    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["language"] == "zh"
    assert call_kwargs["file"].name.endswith(".m4a")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/services/stt/test_openai_whisper_provider.py`
Expected: FAIL — `OpenAIWhisperProvider` not importable.

- [ ] **Step 3: Implement provider**

`deeptutor/services/stt/providers/__init__.py`:
```python
"""STT provider implementations.

Each submodule self-registers via :func:`register_stt_provider`. Importing
this package triggers registration of every shipped provider.
"""

from deeptutor.services.stt.providers import openai_whisper  # noqa: F401  (side-effect)
```

`deeptutor/services/stt/providers/openai_whisper.py`:
```python
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
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
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
```

Update `deeptutor/services/stt/__init__.py` to trigger registration:
```python
"""Speech-to-text service (provider-agnostic)."""

from deeptutor.services.stt.base import STTProvider, STTResult
from deeptutor.services.stt.provider_registry import (
    get_stt_provider,
    register_stt_provider,
)
from deeptutor.services.stt import providers as _providers  # noqa: F401  (registers)

__all__ = ["STTProvider", "STTResult", "get_stt_provider", "register_stt_provider"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/services/stt/test_openai_whisper_provider.py`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add deeptutor/services/stt/providers/__init__.py deeptutor/services/stt/providers/openai_whisper.py deeptutor/services/stt/__init__.py tests/services/stt/test_openai_whisper_provider.py
git commit -m "feat(stt): OpenAI Whisper provider with LLM_* env fallback"
```

---

### Task 4: `POST /api/v1/transcribe` endpoint

**Files:**
- Create: `deeptutor/api/routers/transcribe.py`
- Create: `tests/api/test_transcribe_router.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_transcribe_router.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/api/test_transcribe_router.py`
Expected: FAIL — `deeptutor.api.routers.transcribe` not importable.

- [ ] **Step 3: Implement the router**

`deeptutor/api/routers/transcribe.py`:
```python
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

ALLOWED_AUDIO_MIMES = {
    "audio/webm",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
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
    if len(audio) > _max_bytes():
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds {_max_bytes()} byte limit",
        )

    try:
        provider = get_stt_provider()
        result = await provider.transcribe(
            audio,
            mime_type=mime,
            language=(language or os.environ.get("STT_DEFAULT_LANGUAGE") or None) or None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("STT provider failed")
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc

    return {
        "transcript": result.transcript,
        "language": result.language,
        "duration_ms": result.duration_ms,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/api/test_transcribe_router.py`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add deeptutor/api/routers/transcribe.py tests/api/test_transcribe_router.py
git commit -m "feat(api): POST /api/v1/transcribe endpoint with size + MIME validation"
```

---

### Task 5: Register transcribe router in FastAPI app

**Files:**
- Modify: `deeptutor/api/main.py`

- [ ] **Step 1: Locate the router registration block**

Run: `grep -n "include_router\|router.*prefix" D:/opensource/DeepTutor/deeptutor/api/main.py | head -30`

Expected: a list of `app.include_router(...)` calls. Find the one for `attachments` (most relevant precedent) or for any router under `/api/v1` prefix.

- [ ] **Step 2: Add the transcribe router import + registration**

In `deeptutor/api/main.py`, add to the imports near the other router imports:
```python
from deeptutor.api.routers import transcribe as transcribe_router
```

Add to the registration block, following the same prefix style as `unified_ws` (which lives at `/api/v1/ws`):
```python
app.include_router(transcribe_router.router, prefix="/api/v1", tags=["transcribe"])
```

If the existing `unified_ws` registration uses a different exact pattern, match it precisely.

- [ ] **Step 3: Verify the route exists**

Run:
```bash
python -c "from deeptutor.api.main import app; print([r.path for r in app.routes if 'transcribe' in getattr(r, 'path', '')])"
```
Expected output: `['/api/v1/transcribe']`

- [ ] **Step 4: Commit**

```bash
git add deeptutor/api/main.py
git commit -m "feat(api): wire transcribe router into FastAPI app"
```

---

### Task 6: Document STT env vars in `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the STT block near the LLM block**

Run: `grep -n "^LLM_API_KEY\|^LLM_HOST" D:/opensource/DeepTutor/.env.example | head -5`

Identify the line right after the LLM section. Insert this block:
```bash
# ─── Speech-to-Text (voice input) ───────────────────────────────────────
# Provider selection. Currently only `openai_whisper` ships out of the box.
STT_PROVIDER=openai_whisper
# Falls back to LLM_API_KEY if unset.
STT_API_KEY=
# Falls back to LLM_HOST if unset. Useful for OpenAI-compatible local
# servers (LM Studio, faster-whisper-server, Groq Whisper, etc.).
STT_HOST=
# Whisper model name. The OpenAI hosted endpoint accepts "whisper-1".
# Local servers may expose other model names.
STT_MODEL=whisper-1
# Max audio payload in bytes (default 25 MB). Requests above this return 413.
STT_MAX_BYTES=26214400
# Optional default language hint (ISO 639-1). Empty = auto-detect.
STT_DEFAULT_LANGUAGE=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): document STT_* env vars for voice input"
```

---

### Task 7: `supports_audio()` capability + audio model table

**Files:**
- Modify: `deeptutor/services/llm/capabilities.py`
- Create: `tests/services/llm/test_capabilities_audio.py`

- [ ] **Step 1: Read the existing capabilities module to match style**

Run: `grep -n "supports_vision\|_VISION\|def supports_" D:/opensource/DeepTutor/deeptutor/services/llm/capabilities.py | head -20`

Note the exact naming pattern, table structure, and matching strategy used for vision — mirror it for audio.

- [ ] **Step 2: Write the failing test**

`tests/services/llm/test_capabilities_audio.py`:
```python
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
    assert supports_audio(binding, model) is expected
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/services/llm/test_capabilities_audio.py`
Expected: FAIL — `supports_audio` does not exist.

- [ ] **Step 4: Implement**

Append to `deeptutor/services/llm/capabilities.py`:
```python
# ─── Audio input capability ──────────────────────────────────────────────────
# Models that accept native audio input in chat completions / generation calls.
# Prefix-matched so version suffixes (e.g. "-2026-01-15") still count.
# Phase 2: read overrides from services/model_selection catalog.
_AUDIO_INPUT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-audio-preview", "gpt-4o-mini-audio-preview"],
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
}


def supports_audio(binding: str, model: str | None) -> bool:
    """Return True when the LLM accepts raw audio input (alongside text).

    Used by ``multimodal.prepare_multimodal_messages`` to decide whether
    to forward the raw audio blob along with the STT transcript text.
    """
    if not model:
        return False
    prefixes = _AUDIO_INPUT_MODELS.get((binding or "").lower(), [])
    return any(model == p or model.startswith(p) for p in prefixes)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/services/llm/test_capabilities_audio.py`
Expected: PASS (13 parametrized cases).

- [ ] **Step 6: Commit**

```bash
git add deeptutor/services/llm/capabilities.py tests/services/llm/test_capabilities_audio.py
git commit -m "feat(llm): supports_audio capability + initial model table"
```

---

### Task 8: Extend `multimodal.py` to handle audio attachments

**Files:**
- Modify: `deeptutor/services/llm/multimodal.py`
- Create: `tests/services/llm/test_multimodal_audio.py`

> **Investigation step (do first, before writing tests):** Run `grep -n "gemini\|google\|generative_ai" D:/opensource/DeepTutor/deeptutor/services/llm/provider_core/ -r | head` and `ls D:/opensource/DeepTutor/deeptutor/services/llm/provider_core/`. There's no Gemini-specific provider today — Gemini likely goes through `openai_compat_provider.py`. If so, **drop the Gemini-specific audio part from this task** and only implement the OpenAI `input_audio` form. Update `supports_audio` in Task 7's table to remove the `gemini` entry until Gemini gets a real provider — the test matrix above must be updated correspondingly. **Decide before writing code.**

- [ ] **Step 1: Write the failing test (OpenAI path only; revise after investigation)**

`tests/services/llm/test_multimodal_audio.py`:
```python
"""Tests for audio attachment handling in multimodal message preparation."""

from dataclasses import dataclass

from deeptutor.services.llm.multimodal import prepare_multimodal_messages


@dataclass
class _Attachment:
    type: str
    base64: str = ""
    mime_type: str = ""
    filename: str = ""
    url: str = ""


def _msgs():
    return [{"role": "user", "content": "What did I say?"}]


def test_audio_injected_for_supported_model():
    audio = _Attachment(type="audio", base64="ZmFrZQ==", mime_type="audio/webm",
                        filename="voice.webm")
    result = prepare_multimodal_messages(
        _msgs(), [audio], binding="openai", model="gpt-4o-audio-preview",
    )
    content = result.messages[0]["content"]
    assert isinstance(content, list)
    # Text part still present
    assert any(p.get("type") == "text" and p.get("text") == "What did I say?" for p in content)
    # Audio part present
    audio_parts = [p for p in content if p.get("type") == "input_audio"]
    assert len(audio_parts) == 1
    assert audio_parts[0]["input_audio"]["data"] == "ZmFrZQ=="
    assert audio_parts[0]["input_audio"]["format"] == "webm"
    assert result.audio_dropped == 0


def test_audio_silently_dropped_for_unsupported_model():
    audio = _Attachment(type="audio", base64="ZmFrZQ==", mime_type="audio/webm")
    result = prepare_multimodal_messages(
        _msgs(), [audio], binding="openai", model="gpt-4o",
    )
    # Message unchanged — no audio part, text content preserved
    msg = result.messages[0]
    assert msg["content"] == "What did I say?" or msg["content"] == [
        {"type": "text", "text": "What did I say?"}
    ]
    assert result.audio_dropped == 0  # Not "dropped" — never injected; transcript is fallback


def test_audio_and_image_coexist():
    audio = _Attachment(type="audio", base64="QQ==", mime_type="audio/webm")
    image = _Attachment(type="image", base64="Qg==", mime_type="image/png", filename="x.png")
    result = prepare_multimodal_messages(
        _msgs(), [audio, image], binding="openai", model="gpt-4o-audio-preview",
    )
    content = result.messages[0]["content"]
    types = [p.get("type") for p in content]
    assert "input_audio" in types
    assert "image_url" in types
    assert "text" in types


def test_audio_mime_to_format_mapping():
    cases = [
        ("audio/webm", "webm"),
        ("audio/mp4", "mp4"),
        ("audio/wav", "wav"),
        ("audio/mpeg", "mp3"),
    ]
    for mime, expected_format in cases:
        audio = _Attachment(type="audio", base64="QQ==", mime_type=mime)
        result = prepare_multimodal_messages(
            _msgs(), [audio], binding="openai", model="gpt-4o-audio-preview",
        )
        part = next(p for p in result.messages[0]["content"] if p.get("type") == "input_audio")
        assert part["input_audio"]["format"] == expected_format, mime


def test_no_audio_no_change():
    msgs = [{"role": "user", "content": "hi"}]
    result = prepare_multimodal_messages(msgs, [], binding="openai", model="gpt-4o-audio-preview")
    assert result.messages[0]["content"] == "hi"
    assert result.audio_dropped == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/services/llm/test_multimodal_audio.py`
Expected: FAIL — `audio_dropped` field missing on `MultimodalResult` and no audio handling exists.

- [ ] **Step 3: Modify `multimodal.py`**

In `deeptutor/services/llm/multimodal.py`:

1. Add `audio_dropped: int = 0` to `MultimodalResult` dataclass.
2. Import `supports_audio` from `capabilities`.
3. Add the MIME→format map and audio part builder:

```python
_AUDIO_MIME_TO_FORMAT = {
    "audio/webm": "webm",
    "audio/mp4":  "mp4",
    "audio/x-m4a": "mp4",
    "audio/wav":  "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3":  "mp3",
    "audio/ogg":  "ogg",
}


def _build_openai_audio_part(*, base64_data: str, mime_type: str) -> dict[str, Any]:
    audio_format = _AUDIO_MIME_TO_FORMAT.get((mime_type or "").lower(), "webm")
    return {
        "type": "input_audio",
        "input_audio": {"data": base64_data, "format": audio_format},
    }


def _inject_audio(
    messages: list[dict[str, Any]],
    user_idx: int,
    audio_attachments: list[Any],
) -> None:
    """Append audio content parts to the user message at *user_idx*.

    Caller must have already gated on ``supports_audio()``. Anthropic is
    intentionally unsupported (no public audio-in API today).
    """
    msg = messages[user_idx]
    original_content = msg.get("content", "")

    if isinstance(original_content, str):
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": original_content}]
    elif isinstance(original_content, list):
        content_parts = list(original_content)
    else:
        content_parts = [{"type": "text", "text": str(original_content)}]

    for att in audio_attachments:
        b64 = getattr(att, "base64", "") or ""
        if not b64:
            continue
        mime = getattr(att, "mime_type", "") or "audio/webm"
        content_parts.append(_build_openai_audio_part(base64_data=b64, mime_type=mime))

    messages[user_idx] = {**msg, "content": content_parts}
```

4. In `prepare_multimodal_messages`, after the image-handling block, add:

```python
    audio_attachments = [a for a in (attachments or []) if getattr(a, "type", "") == "audio"]
    if audio_attachments and supports_audio(binding, model):
        last_user_idx = _find_last_user_message(messages)
        if last_user_idx is not None:
            _inject_audio(messages, last_user_idx, audio_attachments)
```

(Place this *after* image handling so audio parts come after image parts in the content array — purely cosmetic but stable for tests.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/services/llm/test_multimodal_audio.py tests/services/llm/test_capabilities_audio.py`
Expected: PASS (all tests). Also run the existing multimodal tests to ensure no regression:
`pytest -q --import-mode=importlib tests/services/llm/`

- [ ] **Step 5: Commit**

```bash
git add deeptutor/services/llm/multimodal.py tests/services/llm/test_multimodal_audio.py
git commit -m "feat(llm): inject audio content parts when model supports_audio"
```

---

### Task 9: Add `build_user_message_with_media` that delegates to `multimodal.py`

> **Pre-task facts (verified before writing this plan):**
> - The current function is `ContextBuilder._build_user_content(self, text: str, media: list[str] | None)` at `deeptutor/tutorbot/agent/context.py:186`. **`media` is a list of file paths**, not attachment dicts. It reads bytes from disk, base64-encodes, and inlines image_url parts.
> - The canonical attachment type is `deeptutor.core.context.Attachment` (dataclass at `deeptutor/core/context.py:16`) with fields `type`, `url`, `base64`, `filename`, `mime_type`, `id`, `extracted_text`. `multimodal.py` is duck-typed against this shape (uses `getattr`).
> - The strategy here: **don't rename or modify `_build_user_content`** (it has existing path-based callers). Add a new public method `build_user_message_with_media(text, attachments)` that takes `list[Attachment]`, calls `multimodal.prepare_multimodal_messages`, and returns the resulting content. The new WS path from `tutorbot-web` constructs `Attachment` objects from inbound base64 frames and calls this new method.

**Files:**
- Modify: `deeptutor/tutorbot/agent/context.py` (add new method; do not remove `_build_user_content`)
- Modify: `deeptutor/tutorbot/agent/loop.py` (forward audio attachments + binding/model to the new method; audit `:1275` image-filter behavior — verify audio is exempt)
- Create: `tests/tutorbot/test_context_media.py`

- [ ] **Step 1: Investigation — confirm loop.py:1275 behavior**

Read `deeptutor/tutorbot/agent/loop.py` around lines 1265–1290 (use Read tool with `offset=1260, limit=40`).

Determine: does this code filter content parts in user messages or assistant messages? If user messages, audio parts must be exempt (we always want them passed through). If assistant only, no action needed — audio never appears in assistant content. **Record the answer here as a code comment in `loop.py`** before continuing, so future readers see the rationale.

- [ ] **Step 2: Investigation — find where TutorBot's WS handler ingests attachments**

Run: `grep -rn "attachments" D:/opensource/DeepTutor/deeptutor/tutorbot/agent/ | grep -v __pycache__`

Identify the spot where inbound WS message attachments are read into the agent loop. That's where the conversion from the wire format (`{type, base64, mime_type, filename}`) into `Attachment(type=..., base64=..., mime_type=..., filename=...)` must happen. The conversion is one line per attachment — list this site in your task notes.

- [ ] **Step 3: Write the failing test**

`tests/tutorbot/__init__.py`: empty file (if it doesn't already exist).

`tests/tutorbot/test_context_media.py`:
```python
"""Tests for ContextBuilder.build_user_message_with_media."""

import base64
from pathlib import Path

import pytest

from deeptutor.core.context import Attachment
from deeptutor.tutorbot.agent.context import ContextBuilder


@pytest.fixture
def builder(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_memory = tmp_path / "memory"
    user_memory.mkdir()
    return ContextBuilder(workspace=workspace, user_memory_dir=user_memory)


def test_no_attachments_returns_plain_text(builder):
    result = builder.build_user_message_with_media(
        text="hello", attachments=[], binding="openai", model="gpt-4o-audio-preview",
    )
    assert result == "hello"


def test_image_attachment_produces_multimodal_array(builder):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    att = Attachment(
        type="image",
        base64=base64.b64encode(png_bytes).decode(),
        mime_type="image/png",
        filename="x.png",
    )
    result = builder.build_user_message_with_media(
        text="describe",
        attachments=[att],
        binding="openai",
        model="gpt-4o",  # vision-capable
    )
    assert isinstance(result, list)
    assert any(p.get("type") == "text" and p.get("text") == "describe" for p in result)
    assert any(p.get("type") == "image_url" for p in result)


def test_audio_injected_for_audio_capable_model(builder):
    att = Attachment(
        type="audio",
        base64="ZmFrZQ==",
        mime_type="audio/webm",
        filename="voice.webm",
    )
    result = builder.build_user_message_with_media(
        text="what did I say",
        attachments=[att],
        binding="openai",
        model="gpt-4o-audio-preview",
    )
    assert isinstance(result, list)
    assert any(p.get("type") == "text" and p.get("text") == "what did I say" for p in result)
    assert any(p.get("type") == "input_audio" for p in result)


def test_audio_dropped_for_non_audio_model(builder):
    att = Attachment(type="audio", base64="ZmFrZQ==", mime_type="audio/webm")
    result = builder.build_user_message_with_media(
        text="what did I say",
        attachments=[att],
        binding="openai",
        model="gpt-4o",  # vision but no audio
    )
    # No audio part injected; text preserved (string OR text-only list both acceptable)
    if isinstance(result, list):
        assert not any(p.get("type") == "input_audio" for p in result)
        assert any(p.get("type") == "text" for p in result)
    else:
        assert result == "what did I say"


def test_path_based_callers_unaffected(builder, tmp_path):
    """The original _build_user_content(text, media: list[str]) path still works
    so existing tutorbot callers that pass file paths are not broken."""
    img_path = tmp_path / "y.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    result = builder._build_user_content(text="see this", media=[str(img_path)])
    assert isinstance(result, list)
    assert any(p.get("type") == "image_url" for p in result)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest -q --import-mode=importlib tests/tutorbot/test_context_media.py`
Expected: FAIL — `build_user_message_with_media` does not exist.

- [ ] **Step 5: Add the new method to `ContextBuilder`**

In `deeptutor/tutorbot/agent/context.py`, add **alongside** the existing `_build_user_content` (do not delete or modify the existing method):

```python
def build_user_message_with_media(
    self,
    text: str,
    attachments: list["Attachment"],
    *,
    binding: str,
    model: str | None,
) -> str | list[dict[str, Any]]:
    """Build user message content from canonical Attachment objects.

    Routes through services/llm/multimodal.py so the same vision/audio
    capability gating used by the chat turn runtime applies here too.
    Returns either a plain string (when no media parts get injected) or
    an OpenAI-style content-parts array.

    For path-based callers (existing tutorbot file uploads), keep using
    ``_build_user_content(text, media: list[str])`` — it remains the
    canonical path for that flow.
    """
    if not attachments:
        return text

    from deeptutor.services.llm.multimodal import prepare_multimodal_messages

    # multimodal mutates the messages list in place; pass a fresh one and
    # extract the post-mutation content.
    messages = [{"role": "user", "content": text}]
    prepare_multimodal_messages(
        messages,
        attachments,
        binding=binding,
        model=model,
    )
    content = messages[0].get("content", text)
    return content if isinstance(content, list) else text
```

Add the import at the top of the file:
```python
from deeptutor.core.context import Attachment
```

- [ ] **Step 6: Wire the WS path to use the new method**

At the call-site identified in Step 2, after attachments are read from the inbound WS frame:

```python
from deeptutor.core.context import Attachment

attachments = [
    Attachment(
        type=a.get("type", ""),
        base64=a.get("base64", ""),
        mime_type=a.get("mime_type", ""),
        filename=a.get("filename", ""),
    )
    for a in inbound_frame.get("attachments", [])
]

# When building the user message for the LLM call:
content = self.context_builder.build_user_message_with_media(
    text=user_text,
    attachments=attachments,
    binding=<active binding>,
    model=<active model>,
)
```

Source the `binding` and `model` from wherever the loop already passes them to the LLM call (same variables — there is no new lookup).

- [ ] **Step 7: Audit `loop.py:1275` per Step 1**

Apply the conclusion: if the existing filter touches user-message content parts, add a branch that preserves `input_audio` parts (matching the existing image preservation logic). If it only touches assistant content, leave as is. Either way, leave a one-line comment explaining the audit outcome.

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest -q --import-mode=importlib tests/tutorbot/test_context_media.py`
Expected: PASS (5 tests).

Re-run the full backend suite to catch regressions:
`pytest -q --import-mode=importlib tests/tutorbot tests/services/llm tests/api`

- [ ] **Step 9: Commit**

```bash
git add deeptutor/tutorbot/agent/context.py deeptutor/tutorbot/agent/loop.py tests/tutorbot/__init__.py tests/tutorbot/test_context_media.py
git commit -m "feat(tutorbot): build_user_message_with_media routes through multimodal layer"
```

---

## Phase 2 — Frontend foundation (refactor only, no new behavior)

### Task 10: Extract `Composer` from `BotChatView`

**Files:**
- Read: `tutorbot-web/components/tutorbot/chat/BotChatView.tsx` (lines around 26, 131, 274–285)
- Create: `tutorbot-web/components/tutorbot/chat/Composer.tsx`
- Modify: `tutorbot-web/components/tutorbot/chat/BotChatView.tsx`

> **Pre-step:** Per `tutorbot-web/AGENTS.md`, before writing any Next.js or React-specific code in this app, skim relevant docs in `tutorbot-web/node_modules/next/dist/docs/`. For this task specifically — there's no Next.js-specific API used, just a React component — but the rule still applies to any file you touch in `tutorbot-web/`.

- [ ] **Step 1: Create the new component**

`tutorbot-web/components/tutorbot/chat/Composer.tsx`:
```tsx
'use client'

import { useState, KeyboardEvent } from 'react'

export type ComposerProps = {
  onSend: (text: string) => void
  disabled?: boolean
  sending?: boolean
  placeholder?: string
}

export function Composer({ onSend, disabled, sending, placeholder }: ComposerProps) {
  const [text, setText] = useState('')

  function handleSend() {
    const trimmed = text.trim()
    if (!trimmed || disabled || sending) return
    onSend(trimmed)
    setText('')
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend = !disabled && !sending && text.trim().length > 0

  return (
    <div className="flex gap-2 items-end">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        rows={1}
        className="flex-1 resize-none rounded border p-2"
      />
      <button
        type="button"
        onClick={handleSend}
        disabled={!canSend}
        className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
      >
        Send
      </button>
    </div>
  )
}
```

(Match the actual className conventions of `BotChatView.tsx` — read the existing JSX at lines 274–285 and mirror the styling exactly. The above is a structural template; preserve the original visual design.)

- [ ] **Step 2: Replace the inline textarea+button in BotChatView**

In `tutorbot-web/components/tutorbot/chat/BotChatView.tsx`:
1. Remove `const [input, setInput] = useState('')` at line 26.
2. Remove the inline `handleSend` body, keep a thin wrapper that just sends the WS message.
3. Replace the JSX block at lines 274–285 with `<Composer onSend={sendMessage} disabled={!connected} sending={sending} placeholder={...} />`.
4. Add `import { Composer } from './Composer'` at the top.

- [ ] **Step 3: Manual smoke**

```bash
python scripts/start_tutorbot_web.py
```

Open `http://localhost:3000`, navigate to a bot's chat, send a message. Verify:
- Text appears in input
- Enter key sends (Shift+Enter for newline)
- Send button enables/disables correctly
- After send, input clears
- Bot replies as before

No visual regression. Take a screenshot for the commit notes.

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/Composer.tsx tutorbot-web/components/tutorbot/chat/BotChatView.tsx
git commit -m "refactor(tutorbot-web): extract Composer from BotChatView"
```

---

### Task 11: Add `Attachment` type and `AttachmentChipRow` scaffold

**Files:**
- Create: `tutorbot-web/components/tutorbot/chat/AttachmentChipRow.tsx`
- Modify: `tutorbot-web/components/tutorbot/chat/Composer.tsx`
- Modify: `tutorbot-web/lib/agent-chat-types.ts` (or wherever shared types live)

- [ ] **Step 1: Add the `Attachment` TS type**

In `tutorbot-web/lib/agent-chat-types.ts` (append near other message types):
```ts
export type Attachment = {
  id: string
  type: 'image' | 'audio'
  filename: string
  mimeType: string
  sizeBytes: number
  base64: string
  previewUrl?: string   // image only
  durationMs?: number   // audio only
  objectUrl?: string    // audio only — for playback in chip
}

export type AttachmentWire = {
  type: 'image' | 'audio'
  filename: string
  mime_type: string
  base64: string
}

export function attachmentToWire(a: Attachment): AttachmentWire {
  return {
    type: a.type,
    filename: a.filename,
    mime_type: a.mimeType,
    base64: a.base64,
  }
}
```

- [ ] **Step 2: Create `AttachmentChipRow.tsx`**

`tutorbot-web/components/tutorbot/chat/AttachmentChipRow.tsx`:
```tsx
'use client'

import type { Attachment } from '../../../lib/agent-chat-types'

export type AttachmentChipRowProps = {
  attachments: Attachment[]
  onRemove: (id: string) => void
}

export function AttachmentChipRow({ attachments, onRemove }: AttachmentChipRowProps) {
  if (attachments.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2 px-2 pb-2">
      {attachments.map((a) => (
        <div
          key={a.id}
          className="flex items-center gap-2 rounded border bg-gray-100 px-2 py-1 text-sm"
        >
          {a.type === 'image' && a.previewUrl && (
            <img src={a.previewUrl} alt={a.filename} className="h-8 w-8 object-cover rounded" />
          )}
          {a.type === 'audio' && (
            <>
              <span aria-hidden>🎤</span>
              {a.objectUrl && <audio src={a.objectUrl} controls className="h-6" />}
              <span>{formatDuration(a.durationMs)}</span>
            </>
          )}
          <span className="max-w-[10rem] truncate">{a.filename}</span>
          <button
            type="button"
            onClick={() => onRemove(a.id)}
            aria-label={`Remove ${a.filename}`}
            className="text-gray-500 hover:text-red-600"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}

function formatDuration(ms: number | undefined): string {
  if (!ms) return ''
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
```

- [ ] **Step 3: Wire empty attachments state into Composer**

In `Composer.tsx`, add state and pass to `AttachmentChipRow`:
```tsx
import { useState, useEffect, KeyboardEvent } from 'react'
import { AttachmentChipRow } from './AttachmentChipRow'
import type { Attachment } from '../../../lib/agent-chat-types'

// ... inside Composer:
const [attachments, setAttachments] = useState<Attachment[]>([])

function removeAttachment(id: string) {
  setAttachments((prev) => {
    const target = prev.find((a) => a.id === id)
    if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl)
    if (target?.objectUrl) URL.revokeObjectURL(target.objectUrl)
    return prev.filter((a) => a.id !== id)
  })
}

// Cleanup on unmount
useEffect(() => {
  return () => {
    attachments.forEach((a) => {
      if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
      if (a.objectUrl) URL.revokeObjectURL(a.objectUrl)
    })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [])
```

Render the chip row above the textarea:
```tsx
return (
  <div>
    <AttachmentChipRow attachments={attachments} onRemove={removeAttachment} />
    {/* existing flex row with textarea + send */}
  </div>
)
```

- [ ] **Step 4: Manual smoke**

Restart `python scripts/start_tutorbot_web.py`, open the chat. Verify:
- Composer renders as before
- No chip row appears (attachments is empty)
- Send still works
- React DevTools (if installed) shows `attachments: []` on Composer

- [ ] **Step 5: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/Composer.tsx tutorbot-web/components/tutorbot/chat/AttachmentChipRow.tsx tutorbot-web/lib/agent-chat-types.ts
git commit -m "feat(tutorbot-web): Attachment type and AttachmentChipRow scaffold"
```

---

## Phase 3 — Image feature

### Task 12: `AttachmentPicker` — file input + validation

**Files:**
- Create: `tutorbot-web/components/tutorbot/chat/AttachmentPicker.tsx`
- Modify: `tutorbot-web/components/tutorbot/chat/Composer.tsx`
- Modify: `tutorbot-web/locales/en/app.json`
- Modify: `tutorbot-web/locales/zh/app.json`

- [ ] **Step 1: Add i18n keys**

Append to `tutorbot-web/locales/en/app.json` (under appropriate root key, matching existing structure):
```json
"composer": {
  "attach": "Attach",
  "attachImage": "Attach image",
  "imageTooLarge": "Image too large (max 10 MB)",
  "imageWrongType": "Unsupported image type"
}
```

Append matching block to `tutorbot-web/locales/zh/app.json`:
```json
"composer": {
  "attach": "附件",
  "attachImage": "上传图片",
  "imageTooLarge": "图片过大 (上限 10 MB)",
  "imageWrongType": "不支持的图片格式"
}
```

(Inspect the existing JSON structure first — if it uses a different nesting convention, follow that.)

- [ ] **Step 2: Create AttachmentPicker**

`tutorbot-web/components/tutorbot/chat/AttachmentPicker.tsx`:
```tsx
'use client'

import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import type { Attachment } from '../../../lib/agent-chat-types'

const MAX_IMAGE_MB = Number(process.env.NEXT_PUBLIC_MAX_IMAGE_MB ?? 10)
const MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024
const ALLOWED_IMAGE_MIMES = new Set([
  'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
])

export type AttachmentPickerProps = {
  onAdd: (attachment: Attachment) => void
  onError: (message: string) => void
}

export function AttachmentPicker({ onAdd, onError }: AttachmentPickerProps) {
  const { t } = useTranslation('app')
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File) {
    const mime = (file.type || '').toLowerCase()
    if (!ALLOWED_IMAGE_MIMES.has(mime)) {
      onError(t('composer.imageWrongType'))
      return
    }
    if (file.size > MAX_IMAGE_BYTES) {
      onError(t('composer.imageTooLarge'))
      return
    }

    const buffer = await file.arrayBuffer()
    const bytes = new Uint8Array(buffer)

    // SVG XSS guard
    if (mime === 'image/svg+xml') {
      const text = new TextDecoder().decode(bytes)
      if (/<script/i.test(text)) {
        onError(t('composer.imageWrongType'))
        return
      }
    }

    const base64 = bytesToBase64(bytes)
    const previewUrl = URL.createObjectURL(file)

    onAdd({
      id: crypto.randomUUID(),
      type: 'image',
      filename: file.name,
      mimeType: mime,
      sizeBytes: file.size,
      base64,
      previewUrl,
    })
  }

  function handleClick() {
    inputRef.current?.click()
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleFile(file)
          e.target.value = ''
        }}
      />
      <button
        type="button"
        onClick={handleClick}
        aria-label={t('composer.attachImage')}
        title={t('composer.attachImage')}
        className="rounded p-2 hover:bg-gray-100"
      >
        📎
      </button>
    </>
  )
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
}
```

- [ ] **Step 3: Wire into Composer**

In `Composer.tsx`:
```tsx
import { AttachmentPicker } from './AttachmentPicker'

// inside Composer body:
function addAttachment(a: Attachment) {
  setAttachments((prev) => [...prev, a])
}
function showError(msg: string) {
  // For v1, browser alert is fine — replace with a toast component in a follow-up.
  // If a toast library already exists in tutorbot-web, prefer it.
  alert(msg)
}

// in the JSX, next to the Send button:
<AttachmentPicker onAdd={addAttachment} onError={showError} />
```

(If `tutorbot-web/` already has a toast/notification component, use it instead of `alert`. Check `tutorbot-web/components/ui/` for an existing one.)

- [ ] **Step 4: Manual smoke**

Restart dev server. In a bot chat:
- Click paperclip → file picker opens
- Select a PNG ≤ 10 MB → chip appears with thumbnail
- Click × on chip → chip removed, no console errors
- Try a 15 MB PNG → error toast/alert
- Try a `.txt` file → error toast/alert
- Try an SVG containing `<script>` → rejected

- [ ] **Step 5: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/AttachmentPicker.tsx tutorbot-web/components/tutorbot/chat/Composer.tsx tutorbot-web/locales/en/app.json tutorbot-web/locales/zh/app.json
git commit -m "feat(tutorbot-web): AttachmentPicker with image file input + validation"
```

---

### Task 13: Paste-from-clipboard + drag-drop for images

**Files:**
- Modify: `tutorbot-web/components/tutorbot/chat/Composer.tsx`
- Modify: `tutorbot-web/components/tutorbot/chat/AttachmentPicker.tsx` (extract the `handleFile` logic into an exported helper)

- [ ] **Step 1: Extract `validateAndAdd` helper from AttachmentPicker**

In `AttachmentPicker.tsx`, export the file-handling logic so Composer can call it from paste/drop handlers:
```tsx
export async function processImageFile(
  file: File,
  onAdd: (a: Attachment) => void,
  onError: (msg: string) => void,
  t: (key: string) => string,
): Promise<void> {
  // (move the body of handleFile here, replacing the inner t() calls)
}
```

Update `AttachmentPicker`'s internal handler to call `processImageFile(file, onAdd, onError, t)`.

- [ ] **Step 2: Wire paste + drop on Composer's root element**

In `Composer.tsx`, add handlers and a drop-overlay state:
```tsx
import { processImageFile } from './AttachmentPicker'

const [isDragging, setIsDragging] = useState(false)
const { t } = useTranslation('app')

async function handlePaste(e: React.ClipboardEvent) {
  for (const item of e.clipboardData.items) {
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file && file.type.startsWith('image/')) {
        e.preventDefault()
        await processImageFile(file, addAttachment, showError, t)
      }
    }
  }
}

function handleDragOver(e: React.DragEvent) {
  e.preventDefault()
  setIsDragging(true)
}
function handleDragLeave(e: React.DragEvent) {
  e.preventDefault()
  setIsDragging(false)
}
async function handleDrop(e: React.DragEvent) {
  e.preventDefault()
  setIsDragging(false)
  for (const file of Array.from(e.dataTransfer.files)) {
    if (file.type.startsWith('image/')) {
      await processImageFile(file, addAttachment, showError, t)
    }
  }
}
```

Apply to the Composer root:
```tsx
<div
  onPaste={handlePaste}
  onDragOver={handleDragOver}
  onDragLeave={handleDragLeave}
  onDrop={handleDrop}
  className={isDragging ? 'border-2 border-dashed border-blue-500' : ''}
>
  ...
</div>
```

- [ ] **Step 3: Manual smoke**

Restart dev server:
- Take a screenshot, Ctrl/⌘+V into composer → chip appears
- Drag an image file from desktop onto composer → overlay shows, drop → chip appears
- Drag a non-image file → no chip added (no error required, just ignored)

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/AttachmentPicker.tsx tutorbot-web/components/tutorbot/chat/Composer.tsx
git commit -m "feat(tutorbot-web): image paste + drag-drop in composer"
```

---

### Task 14: Extend `lib/unified-ws.ts` to accept attachments + wire Composer send

**Files:**
- Read: `tutorbot-web/lib/unified-ws.ts` (find the `sendMessage` function — `wc -l` showed 287 lines)
- Modify: `tutorbot-web/lib/unified-ws.ts`
- Modify: `tutorbot-web/components/tutorbot/chat/Composer.tsx`
- Modify: `tutorbot-web/components/tutorbot/chat/BotChatView.tsx`

- [ ] **Step 1: Read current sendMessage**

Run: `grep -n "sendMessage\|function send\|export.*function" D:/opensource/DeepTutor/tutorbot-web/lib/unified-ws.ts | head -10`

Note the current signature and how the WS frame is constructed. The extension must be additive — existing callers pass no attachments.

- [ ] **Step 2: Extend the signature**

In `tutorbot-web/lib/unified-ws.ts`, change the signature of the function that sends user messages. Example pattern (adjust to actual API):
```ts
import type { AttachmentWire } from './agent-chat-types'

export function sendMessage(text: string, opts?: { attachments?: AttachmentWire[] }) {
  const frame: Record<string, unknown> = {
    type: 'user_message',
    text,
  }
  if (opts?.attachments && opts.attachments.length > 0) {
    frame.attachments = opts.attachments
  }
  ws.send(JSON.stringify(frame))
}
```

(Match the actual function structure — there may be session_id/bot_id/etc. already included. The change is just adding the `attachments` field to the frame when present.)

- [ ] **Step 3: Composer passes attachments on send**

In `Composer.tsx`, change `onSend` signature to also pass attachments:
```tsx
export type ComposerProps = {
  onSend: (text: string, attachments: Attachment[]) => void
  // ...
}

function handleSend() {
  const trimmed = text.trim()
  if ((!trimmed && attachments.length === 0) || disabled || sending) return
  onSend(trimmed, attachments)
  setText('')
  // Revoke and clear attachments
  attachments.forEach((a) => {
    if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
    if (a.objectUrl) URL.revokeObjectURL(a.objectUrl)
  })
  setAttachments([])
}

const canSend = !disabled && !sending && (text.trim().length > 0 || attachments.length > 0)
```

- [ ] **Step 4: BotChatView forwards to sendMessage**

In `BotChatView.tsx`, update the `onSend` prop wiring:
```tsx
import { attachmentToWire } from '../../../lib/agent-chat-types'

<Composer
  onSend={(text, attachments) =>
    sendMessage(text, { attachments: attachments.map(attachmentToWire) })
  }
  // ... other props
/>
```

- [ ] **Step 5: Manual smoke**

Restart dev server. In a bot chat with a vision-capable model (e.g. `gpt-4o`):
- Attach a PNG, type "what's in this image?", send
- Open DevTools → Network → WS frames. Verify the outgoing frame contains `attachments: [{type: 'image', mime_type: 'image/png', base64: '...', filename: '...'}]`
- Bot reply should describe the image

If using a non-vision model, expect the existing "images stripped" warning event from `multimodal.py`.

- [ ] **Step 6: Commit**

```bash
git add tutorbot-web/lib/unified-ws.ts tutorbot-web/components/tutorbot/chat/Composer.tsx tutorbot-web/components/tutorbot/chat/BotChatView.tsx
git commit -m "feat(tutorbot-web): wire image attachments through WS to TutorBot"
```

---

## Phase 4 — Voice feature

### Task 15: `lib/transcribe-api.ts` — POST helper for `/api/v1/transcribe`

**Files:**
- Create: `tutorbot-web/lib/transcribe-api.ts`

- [ ] **Step 1: Identify the proxy/fetch convention**

Run: `grep -n "fetch\|/api/" D:/opensource/DeepTutor/tutorbot-web/lib/*.ts | head -20`

Note how other lib files call backend APIs (proxy path, base URL handling, error mapping). Mirror that pattern.

- [ ] **Step 2: Implement the helper**

`tutorbot-web/lib/transcribe-api.ts`:
```ts
export type TranscribeResult = {
  transcript: string
  language?: string
  durationMs?: number
}

export async function transcribe(
  blob: Blob,
  opts?: { language?: string; signal?: AbortSignal },
): Promise<TranscribeResult> {
  const form = new FormData()
  form.append('file', blob, `voice.${extFromMime(blob.type)}`)
  if (opts?.language) form.append('language', opts.language)

  const resp = await fetch('/api/v1/transcribe', {
    method: 'POST',
    body: form,
    signal: opts?.signal,
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    throw new TranscribeError(resp.status, body || `HTTP ${resp.status}`)
  }
  const json = (await resp.json()) as {
    transcript: string
    language?: string | null
    duration_ms?: number | null
  }
  return {
    transcript: json.transcript,
    language: json.language ?? undefined,
    durationMs: json.duration_ms ?? undefined,
  }
}

export class TranscribeError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'TranscribeError'
  }
}

function extFromMime(mime: string): string {
  const m = mime.toLowerCase()
  if (m.includes('webm')) return 'webm'
  if (m.includes('mp4')) return 'm4a'
  if (m.includes('wav')) return 'wav'
  if (m.includes('mpeg') || m.includes('mp3')) return 'mp3'
  return 'bin'
}
```

(If `tutorbot-web/` uses a path-rewriting proxy via `tutorbot-web/proxy.ts`, the URL may need to be relative to that proxy base — check by reading `proxy.ts` and matching how other lib files compose URLs.)

- [ ] **Step 3: Commit**

```bash
git add tutorbot-web/lib/transcribe-api.ts
git commit -m "feat(tutorbot-web): transcribe API client for /api/v1/transcribe"
```

---

### Task 16: `MicButton` — record, transcribe, hand back

**Files:**
- Create: `tutorbot-web/components/tutorbot/chat/MicButton.tsx`
- Modify: `tutorbot-web/locales/en/app.json`
- Modify: `tutorbot-web/locales/zh/app.json`

- [ ] **Step 1: Add i18n keys**

Append to `composer` block in both locale files:

EN:
```json
"recordVoice": "Record voice",
"stopRecording": "Stop recording",
"recordingTooLong": "Recording too long",
"transcribing": "Transcribing...",
"transcribeFailed": "Couldn't transcribe — try again",
"noSpeechDetected": "No speech detected",
"micDenied": "Microphone access denied — check browser settings"
```

ZH:
```json
"recordVoice": "录音",
"stopRecording": "停止录音",
"recordingTooLong": "录音过长",
"transcribing": "识别中...",
"transcribeFailed": "语音识别失败，请重试",
"noSpeechDetected": "未检测到语音",
"micDenied": "麦克风访问被拒绝，请检查浏览器设置"
```

- [ ] **Step 2: Create MicButton**

`tutorbot-web/components/tutorbot/chat/MicButton.tsx`:
```tsx
'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { transcribe, TranscribeError } from '../../../lib/transcribe-api'

const MAX_RECORDING_MS = 60_000
const PREFERRED_MIMES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
] as const

export type MicButtonProps = {
  onTranscribed: (transcript: string, blob: Blob, mimeType: string, durationMs: number) => void
  onError: (msg: string) => void
  disabled?: boolean
  language?: string
}

type MicState =
  | { kind: 'idle' }
  | { kind: 'requesting' }
  | { kind: 'recording'; startedAt: number; recorder: MediaRecorder; chunks: Blob[]; stream: MediaStream }
  | { kind: 'uploading' }
  | { kind: 'denied' }

function pickMime(): string | undefined {
  for (const m of PREFERRED_MIMES) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) return m
  }
  return undefined
}

export function MicButton({ onTranscribed, onError, disabled, language }: MicButtonProps) {
  const { t } = useTranslation('app')
  const [state, setState] = useState<MicState>({ kind: 'idle' })
  const stopTimerRef = useRef<number | null>(null)
  const elapsedRef = useRef<number>(0)
  const [elapsed, setElapsed] = useState(0)

  // Elapsed counter while recording
  useEffect(() => {
    if (state.kind !== 'recording') return
    const id = window.setInterval(() => {
      const ms = Date.now() - state.startedAt
      elapsedRef.current = ms
      setElapsed(ms)
    }, 200)
    return () => window.clearInterval(id)
  }, [state])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (stopTimerRef.current) window.clearTimeout(stopTimerRef.current)
      if (state.kind === 'recording') {
        state.recorder.stop()
        state.stream.getTracks().forEach((t) => t.stop())
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function startRecording() {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices) {
      onError(t('composer.transcribeFailed'))
      return
    }
    setState({ kind: 'requesting' })
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = pickMime()
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks: Blob[] = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
        stream.getTracks().forEach((t) => t.stop())
        void uploadAndHandOff(blob, recorder.mimeType || 'audio/webm', elapsedRef.current)
      }
      stopTimerRef.current = window.setTimeout(() => {
        if (recorder.state === 'recording') {
          onError(t('composer.recordingTooLong'))
          recorder.stop()
        }
      }, MAX_RECORDING_MS)
      recorder.start()
      setState({ kind: 'recording', startedAt: Date.now(), recorder, chunks, stream })
    } catch {
      setState({ kind: 'denied' })
      onError(t('composer.micDenied'))
    }
  }

  function stopRecording() {
    if (state.kind !== 'recording') return
    if (stopTimerRef.current) {
      window.clearTimeout(stopTimerRef.current)
      stopTimerRef.current = null
    }
    state.recorder.stop()
    setState({ kind: 'uploading' })
  }

  async function uploadAndHandOff(blob: Blob, mimeType: string, durationMs: number) {
    try {
      const result = await transcribe(blob, { language })
      if (!result.transcript.trim()) {
        onError(t('composer.noSpeechDetected'))
        setState({ kind: 'idle' })
        return
      }
      onTranscribed(result.transcript, blob, mimeType, durationMs)
    } catch (err) {
      if (err instanceof TranscribeError) {
        onError(t('composer.transcribeFailed'))
      } else {
        onError(t('composer.transcribeFailed'))
      }
    } finally {
      setState({ kind: 'idle' })
      setElapsed(0)
    }
  }

  function handleClick() {
    if (disabled) return
    if (state.kind === 'idle' || state.kind === 'denied') {
      void startRecording()
    } else if (state.kind === 'recording') {
      stopRecording()
    }
  }

  const isRecording = state.kind === 'recording'
  const isBusy = state.kind === 'requesting' || state.kind === 'uploading'

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || isBusy}
      aria-label={isRecording ? t('composer.stopRecording') : t('composer.recordVoice')}
      title={isRecording ? t('composer.stopRecording') : t('composer.recordVoice')}
      className={`rounded p-2 hover:bg-gray-100 ${isRecording ? 'text-red-600 animate-pulse' : ''}`}
    >
      {isRecording ? `■ ${formatElapsed(elapsed)}` : '🎤'}
    </button>
  )
}

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
```

- [ ] **Step 3: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/MicButton.tsx tutorbot-web/locales/en/app.json tutorbot-web/locales/zh/app.json
git commit -m "feat(tutorbot-web): MicButton with MediaRecorder + transcribe round-trip"
```

---

### Task 17: Wire `MicButton` into Composer (transcript merge + audio attachment)

**Files:**
- Modify: `tutorbot-web/components/tutorbot/chat/Composer.tsx`

- [ ] **Step 1: Import and place MicButton**

```tsx
import { MicButton } from './MicButton'

// inside Composer:
function handleVoiceTranscribed(transcript: string, blob: Blob, mimeType: string, durationMs: number) {
  setText((prev) => (prev.trim() ? `${prev} ${transcript}` : transcript))
  void blobToBase64(blob).then((base64) => {
    addAttachment({
      id: crypto.randomUUID(),
      type: 'audio',
      filename: `voice.${extFromMime(mimeType)}`,
      mimeType,
      sizeBytes: blob.size,
      base64,
      durationMs,
      objectUrl: URL.createObjectURL(blob),
    })
  })
}

// In the JSX next to AttachmentPicker:
<MicButton
  onTranscribed={handleVoiceTranscribed}
  onError={showError}
  disabled={disabled}
  language={navigator?.language?.split('-')?.[0]}
/>
```

Helper functions in the same file:
```ts
async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
}

function extFromMime(mime: string): string {
  const m = (mime || '').toLowerCase()
  if (m.includes('webm')) return 'webm'
  if (m.includes('mp4')) return 'm4a'
  if (m.includes('wav')) return 'wav'
  if (m.includes('mpeg') || m.includes('mp3')) return 'mp3'
  return 'bin'
}
```

- [ ] **Step 2: Manual smoke**

Restart dev server. In a bot chat:
- Click mic → browser asks permission → grant
- Speak for ~5 seconds → click stop
- Transcript appears in composer; audio chip appears with playback
- Edit transcript if desired
- Send → backend receives both text and audio attachment in the WS frame (verify in DevTools → Network → WS)

- [ ] **Step 3: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/Composer.tsx
git commit -m "feat(tutorbot-web): voice transcript fills composer + audio attached for send"
```

---

## Phase 5 — Integration testing

### Task 18: Full manual smoke checklist

**Files:** (no code; verification only)

- [ ] **Step 1: Restart everything fresh**

```bash
python scripts/start_tutorbot_web.py
```

- [ ] **Step 2: Walk through the spec's manual smoke checklist**

For each item, take a screenshot or note pass/fail:

1. Chrome: record voice → transcript appears → edit → send → bot acknowledges spoken content.
2. Safari: same flow (verifies MediaRecorder mp4 fallback).
3. Browser-denied mic: button shows denied state, no crash.
4. Record > 60s: forced stop + "recording too long" toast.
5. Paste image from clipboard: chip appears → send → bot describes image.
6. Drag-drop image: chip appears.
7. Image + voice in same message: bot's reply references both.
8. Switch to a text-only local model: image stripped warning appears; audio silently dropped; behavior consistent.
9. Switch to `gpt-4o-audio-preview` (set in bot settings or env): record voice → confirm both audio and transcript reach the model (verify in backend logs: `audio_dropped=0`).

- [ ] **Step 3: Run the full backend test suite**

```bash
pytest -q --import-mode=importlib \
  tests/api tests/cli tests/services/test_model_catalog.py \
  tests/services/test_path_service.py tests/services/memory \
  tests/services/session tests/tools \
  tests/services/stt tests/services/llm tests/tutorbot
```

Expected: all pass.

- [ ] **Step 4: Run pre-commit on changed files**

```bash
pre-commit run --files \
  deeptutor/services/stt/*.py deeptutor/services/stt/providers/*.py \
  deeptutor/services/llm/multimodal.py deeptutor/services/llm/capabilities.py \
  deeptutor/api/routers/transcribe.py deeptutor/api/main.py \
  deeptutor/tutorbot/agent/context.py deeptutor/tutorbot/agent/loop.py \
  tests/services/stt/*.py tests/services/llm/test_multimodal_audio.py \
  tests/services/llm/test_capabilities_audio.py tests/api/test_transcribe_router.py \
  tests/tutorbot/test_context_media.py
```

Expected: clean pass (or warnings only, per CLAUDE.md — CI is strict but local can warn).

- [ ] **Step 5: Lint frontend**

```bash
cd tutorbot-web && npm run lint
```

Expected: no errors.

- [ ] **Step 6: Commit any final fixes**

If smoke uncovered minor issues, commit them now under appropriate `fix(...)` messages.

---

## Cross-cutting notes

- **Branch & PR target.** Work commits land on `chatV2` (per `gitStatus` at session start). The eventual PR targets `dev` per `CONTRIBUTING.md`.
- **No new dependencies.** `openai` SDK already in `pyproject.toml`. No frontend npm additions.
- **Spec open questions handled inline:**
  - Q1 (Gemini audio shape): Task 8's investigation step decides whether to drop the Gemini entry. If dropped, also remove `gemini` rows from Task 7's test table.
  - Q2 (auth on `/api/v1/transcribe`): The endpoint inherits FastAPI app middleware via `include_router` in Task 5. Verify during smoke that an unauthenticated request behaves the same as other `/api/v1/*` routes.
  - Q3 (`loop.py:1275` image filter): Investigated in Task 9 Step 1.
- **Phase 2 follow-ups** (out of scope for this plan): persist TutorBot-path attachments to `attachment_store`, preview drawer with audio playback, voice in legacy `web/`, document attachments (PDF/DOCX/...), TTS for replies, streaming STT.
