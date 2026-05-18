# Multi-Modal Input (Images + Voice) — Design

**Date:** 2026-05-18
**Branch:** chatV2
**Frontend:** `tutorbot-web/` (the chatV2 frontend)
**Status:** Approved for implementation planning

## Problem

The `tutorbot-web/` composer is text-only. Users cannot attach images (math problems, diagrams, screenshots) or speak to their tutor. The legacy `web/` frontend already supports image attachments end-to-end (composer → `attachment_store` → `services/llm/multimodal.py` → vision-capable LLMs), but `tutorbot-web/`'s `BotChatView` ships none of that, and voice input does not exist anywhere in the codebase.

This spec covers two coordinated subsystems landed together on the chatV2 branch:

1. **Image attachments in `tutorbot-web/`** — port the existing image flow to the new composer using the TutorBot agent path (`tutorbot/agent/context.py` already builds multimodal messages from base64 images).
2. **Voice input (STT)** — a brand-new pipeline: browser-side `MediaRecorder` → server-side transcription via a pluggable `STTProvider` → editable transcript filled into the composer. When the active LLM supports native audio input, the raw audio blob is *also* forwarded alongside the transcript for maximum fidelity.

## Decisions

These were settled during brainstorming and are binding for the implementation plan.

| ID | Decision | Notes |
|----|----------|-------|
| **Scope-S1** | Surface: `tutorbot-web/` only (no legacy `web/` changes in this PR). | Voice and image-in-tutorbot land together; legacy `web/` already has images. |
| **Scope-S2** | Attachment types: images only (PNG/JPG/GIF/WebP/SVG) + audio. | No PDF/DOCX/XLSX/PPTX in v1; defer to a follow-up that wires the existing `document_extractor` path. |
| **STT-L1** | STT runs server-side via provider API. | Mirrors `services/search/` and `services/embedding/` architecture; works in any browser; bilingual EN/ZH out of the box. No browser-native Web Speech API. |
| **STT-U1** | Voice UX: tap → record → tap stop → transcript fills the composer → user edits → user sends. | Batch (non-streaming) STT. No voice-activity detection in v1. 60-second soft cap on recordings. |
| **STT-A1** | When the active LLM supports native audio input, the raw audio blob is sent **alongside** the transcript text. | STT always runs (cheap, gives the user something editable). Audio passthrough is purely additive — capable models see both signals; incapable models see just the (possibly edited) text. |
| **STT-M1** | Transcript-merge rule: if composer is empty, replace; if not empty, append with a space separator. | Natural for both "speak only" and "type then add voice" patterns. |
| **Arch-A** | Approach A — reuse `attachment_store` semantics (in-flight, not in v1 for TutorBot), new `POST /api/v1/transcribe` endpoint, new `services/stt/` package with Protocol from day one. | Rejected B (base64 over WS for everything — loses persistence semantics, large payloads) and C (audio as first-class attachment with server-side STT-then-inject — incompatible with the chosen edit-before-send UX). |
| **URL** | New endpoint: `POST /api/v1/transcribe` (versioned, matches `/api/v1/ws`). | Preserves a path to add streaming STT in v2 without breaking older clients. |
| **Persist-1** | Audio is **not** persisted to `attachment_store` in v1. | Phase 2 work; mirrors what `turn_runtime.py:752` does for the non-TutorBot path. Images also are not persisted on the TutorBot path in v1 — both rely on inline base64 in the WS frame. |
| **Cap-1** | Audio capability table is hardcoded in `services/llm/capabilities.py`. | Initial set: `openai/gpt-4o-audio-*`, `gemini/gemini-2.*`. Hook for `services/model_selection/` override deferred. |

### Deliberately out of scope (Phase 2+)

- Persisting TutorBot-path attachments to `attachment_store` (parity with `turn_runtime.py:752`).
- Preview drawer with audio playback (matching `web/`'s `FilePreviewDrawer.tsx`).
- Voice input in legacy `web/`.
- Document attachments (PDF, DOCX, XLSX, PPTX, text, code, SVG content extraction).
- TTS for assistant replies.
- Streaming STT (interim transcripts shown while recording).
- Voice-activity detection / auto-send on silence.
- A second STT provider (Deepgram, local Whisper, Gemini audio). The Protocol is built to make this a one-file addition.

## Architecture

```
┌─────────────────────────── tutorbot-web ───────────────────────────┐
│                                                                    │
│  BotChatView (slimmed)                                             │
│    └─ Composer (new)                                               │
│        ├─ AttachmentChipRow (new)                                  │
│        ├─ <textarea>                                               │
│        ├─ AttachmentPicker (new) ───── image file/paste/drag       │
│        └─ MicButton (new)                                          │
│            ├─ MediaRecorder                                        │
│            └─ on stop: POST /api/v1/transcribe ──→ transcript      │
│                                                    fills composer  │
│                                                                    │
│  On send: WS message carries text + attachments                    │
│           [{type: 'image'|'audio', base64, mime_type, filename}]   │
└──────────────────────────────────────┬─────────────────────────────┘
                                       │
┌──────────────────────────────────────▼─────────────────────────────┐
│  Backend                                                           │
│                                                                    │
│  POST /api/v1/transcribe (new)                                     │
│    └─ services/stt/ (new)                                          │
│        ├─ STTProvider (Protocol)                                   │
│        ├─ STTResult (dataclass)                                    │
│        └─ providers/openai_whisper.py (v1 impl)                    │
│                                                                    │
│  unified_ws.py → TutorBot turn handler                             │
│    └─ tutorbot/agent/context.py                                    │
│        └─ build_user_message_with_media() (renamed from            │
│           build_user_message_with_images, delegates to             │
│           services/llm/multimodal.py)                              │
│                                                                    │
│  services/llm/multimodal.py — EXTENDED                             │
│    ├─ prepare_multimodal_messages() handles audio parts            │
│    ├─ _build_openai_audio_part(), _build_gemini_audio_part()       │
│    └─ _inject_audio() — gates on supports_audio()                  │
│                                                                    │
│  services/llm/capabilities.py — EXTENDED                           │
│    └─ supports_audio(binding, model) + _AUDIO_INPUT_MODELS table   │
└────────────────────────────────────────────────────────────────────┘
```

### Data flows

**Flow A — image attachment.** AttachmentPicker validates MIME + size → reads file via FileReader → base64 + thumbnail object URL → attachment chip in composer. On Send, WS frame `{ text, attachments: [{type: 'image', base64, mime_type, filename}] }`. Backend's TutorBot context builder delegates to `multimodal.prepare_multimodal_messages()`. Vision-capable model → `image_url` content part injected. Vision-incapable model → image stripped, existing warning event emitted ("Model X can't see images — sent text only").

**Flow B — voice.** MicButton tap → `getUserMedia({audio: true})` → `MediaRecorder` with first-supported mime from `['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']`. Tap stop (or 60s forced stop) → POST blob to `/api/v1/transcribe` as multipart → `services/stt/` provider transcribes → returns `{transcript, language?, duration_ms?}` → MicButton calls `onTranscribed(transcript, blob, mimeType)` → Composer merges transcript into text per STT-M1 and pushes audio as a pending `Attachment` with `type: 'audio'`. On Send, WS frame carries both text and audio attachment. Backend: `multimodal.prepare_multimodal_messages()` calls `supports_audio(binding, model)`. If true → audio content part injected (OpenAI `input_audio` or Gemini inline audio) **alongside** the text. If false → audio dropped silently (the transcript text in the message body is the fallback, so no warning).

**Crossing flow.** Voice + image in the same message is supported by composition — the `attachments` array can hold multiple entries of any type.

### MicButton state machine

```
  idle ──tap──▶ requesting ──grant──▶ recording ──tap──▶ uploading
   ▲              │ deny                  │ 60s cap         │
   │              ▼                       ▼                 │
   └──────── denied                  recording (toast)      │
       (one-time toast,                                     ▼
        button reruns prompt)                          transcribed
                                                            │
                                                            ▼
                                                        idle (input filled)
```

Always release MediaStream tracks on stop (`stream.getTracks().forEach(t => t.stop())`) so the OS mic indicator clears.

## Backend components

### New: `deeptutor/services/stt/` package

Five files mirroring `services/search/`:

```
deeptutor/services/stt/
├── __init__.py                    # re-exports STTProvider, STTResult, get_stt_provider
├── base.py                        # Protocol + dataclass
├── provider_registry.py           # register/get
├── providers/
│   ├── __init__.py                # triggers self-registration
│   └── openai_whisper.py          # v1 impl
```

**`base.py`:**

```python
@dataclass
class STTResult:
    transcript: str
    language: str | None = None
    duration_ms: int | None = None
    raw: dict | None = None

@runtime_checkable
class STTProvider(Protocol):
    name: str
    async def transcribe(
        self, audio: bytes, *, mime_type: str, language: str | None = None,
    ) -> STTResult: ...
```

**`provider_registry.py`** — `register_stt_provider(name, cls)` + `get_stt_provider()`. `get_stt_provider()` reads `STT_PROVIDER` (default `"openai_whisper"`), raises `ConfigurationError` from `deeptutor/core/errors.py` if unknown.

**`providers/openai_whisper.py`** — `OpenAIWhisperProvider` uses the existing `openai` SDK (top-level dep at `pyproject.toml:19`). Reads `STT_API_KEY` (fallback: `LLM_API_KEY`), `STT_HOST` (fallback: `LLM_HOST`), `STT_MODEL` (default `whisper-1`). Calls `client.audio.transcriptions.create(file=..., model=..., language=..., response_format="verbose_json")` to get language + duration. Maps MIME → file extension (`audio/webm → .webm`, `audio/mp4 → .m4a`, `audio/wav → .wav`, `audio/mpeg → .mp3`, else `.bin`) because the OpenAI SDK uses the filename extension to drive server-side decoding.

Compatible with OpenAI-compatible local servers (LM Studio, faster-whisper-server, Groq Whisper) via `STT_HOST`/`LLM_HOST` — important because many DeepTutor users already run local LLM servers.

### New: `deeptutor/api/routers/transcribe.py`

```python
@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
) -> dict:
    # 1. Validate mime_type against ALLOWED_AUDIO_MIMES
    # 2. Validate size against STT_MAX_BYTES (default 25 MB)
    # 3. provider = get_stt_provider()
    # 4. result = await provider.transcribe(audio_bytes, mime_type=..., language=language)
    # 5. Return {"transcript": ..., "language": ..., "duration_ms": ...}
```

Registered in `deeptutor/api/main.py` under prefix `/api/v1`. Error codes: 413 (oversize), 415 (bad MIME), 502 (provider failure with `STTProviderError` translation).

### Modified: `deeptutor/services/llm/capabilities.py`

```python
_AUDIO_INPUT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-audio-preview", "gpt-4o-mini-audio-preview"],
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
}

def supports_audio(binding: str, model: str | None) -> bool:
    if not model:
        return False
    prefixes = _AUDIO_INPUT_MODELS.get((binding or "").lower(), [])
    return any(model == p or model.startswith(p) for p in prefixes)
```

Prefix match (not exact) so version suffixes like `gpt-4o-audio-preview-2026-01-15` work. Code comment: *"Phase 2: read overrides from services/model_selection catalog."*

### Modified: `deeptutor/services/llm/multimodal.py`

Extend `prepare_multimodal_messages()` to also recognize `attachment.type == "audio"`:

- Add `_build_openai_audio_part(base64_data, mime_type)` → `{"type": "input_audio", "input_audio": {"data": ..., "format": <derived from mime>}}`.
- Add `_build_gemini_audio_part(base64_data, mime_type)` → shape determined by inspection of the existing Gemini provider converter during implementation; do not guess from training data.
- Add `_inject_audio(messages, user_idx, audio_attachments, *, binding, model)` mirroring `_inject_images()`. Gates on `supports_audio(binding, model)`. On capable model, appends audio part(s) to user message content. On incapable model, silently drops (no warning event — the transcript text is already in the message and serves as the fallback).
- `MultimodalResult` gains `audio_dropped: int = 0`.

### Modified: `deeptutor/tutorbot/agent/context.py`

Rename `build_user_message_with_images()` → `build_user_message_with_media()`. Current implementation inlines image base64 directly in OpenAI multimodal format (`context.py:202`). Refactor to construct an `Attachment` list and delegate to `multimodal.prepare_multimodal_messages()`. This eliminates the duplicated multimodal-encoding logic between TutorBot and the chat turn runtime path — they share the canonical implementation.

Audit `tutorbot/agent/loop.py:1275` (existing image filtering for some prompt-pruning case) — confirm the same logic should apply to audio parts, or that audio parts are exempt (likely exempt — audio is the user's input, not the assistant's, so pruning logic probably doesn't apply, but verify during implementation).

### Modified: `deeptutor/tutorbot/agent/tools/message.py:63`

Schema description already says "list of file paths to attach (images, audio, documents)". Verify no validation rejects `audio/*` MIMEs; loosen if so.

### New env vars (documented in `.env.example`)

```
STT_PROVIDER=openai_whisper       # provider key
STT_API_KEY=                      # falls back to LLM_API_KEY
STT_HOST=                         # falls back to LLM_HOST (OpenAI-compatible servers)
STT_MODEL=whisper-1
STT_MAX_BYTES=26214400            # 25 MB
STT_DEFAULT_LANGUAGE=             # empty = auto-detect
```

Thread through `services/config/EnvStore` (the pattern used by existing `LLM_*` and `EMBEDDING_*` vars).

## Frontend components

> **Reminder:** `tutorbot-web/` uses a pre-release Next.js whose APIs differ from training data. The implementing agent must consult `tutorbot-web/node_modules/next/dist/docs/` before writing any Next.js-specific code, per `tutorbot-web/AGENTS.md`.

### Component tree

```
BotChatView (existing, slimmed)
└─ Composer (new)
   ├─ AttachmentChipRow (new) — renders pending attachments above input
   ├─ <textarea> (moves from BotChatView)
   ├─ AttachmentPicker (new) — paperclip icon
   └─ MicButton (new) — mic icon, becomes stop button while recording
```

### `Composer.tsx`

Owns: `text` state, `attachments: Attachment[]` state, `handleSend`, `handleAttachmentAdd`, `handleAttachmentRemove`, `handleVoiceTranscribed`.

**`Attachment` shape (frontend):**

```ts
type Attachment = {
  id: string                  // uuid for keying + remove
  type: 'image' | 'audio'
  filename: string
  mimeType: string
  sizeBytes: number
  base64: string              // raw base64, no data: prefix
  previewUrl?: string         // image only — object URL for thumbnail
  durationMs?: number         // audio only
  objectUrl?: string          // audio only — for in-chip playback
}
```

`handleSend` builds the WS payload as `{ text, attachments: attachments.map(toWireFormat) }` via `lib/unified-ws.ts`'s `sendMessage`. On success: clear text, revoke object URLs, clear attachments.

`handleVoiceTranscribed(transcript, blob, mimeType)` implements STT-M1: `text = text.trim() ? `${text} ${transcript}` : transcript`. Pushes the blob as a new `Attachment` of `type: 'audio'`.

### `AttachmentPicker.tsx`

Renders paperclip button. Internally:

- Hidden `<input type="file" accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml" />`, triggered programmatically.
- Listens for `paste` on the composer (Ctrl/⌘+V image paste).
- Listens for `dragenter/dragover/drop` on the composer (drag-and-drop). Visual: 2px dashed overlay during drag.
- All three paths funnel into `validateAndAdd(file)`:
  - MIME in allowed list
  - Size ≤ `NEXT_PUBLIC_MAX_IMAGE_MB` (default 10)
  - SVGs containing `<script` are rejected (cheap XSS guard for the `<img>` rendering path)

No upload happens here — base64 lives in component state until `handleSend`.

### `MicButton.tsx`

Props: `onTranscribed(transcript: string, blob: Blob, mimeType: string)`, `disabled`, `language?: string` (from i18n locale).

State (matches the state machine above):

```ts
type MicState =
  | { kind: 'idle' }
  | { kind: 'requesting' }
  | { kind: 'recording'; startedAt: number; recorder: MediaRecorder; chunks: Blob[]; stream: MediaStream }
  | { kind: 'uploading' }
  | { kind: 'denied' }
```

Transitions:

- Tap `idle` → `getUserMedia({ audio: true })` → pick first supported mimeType from `['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']` (Safari fallback to mp4) → `new MediaRecorder(stream, {mimeType})` → set 60s forced-stop timer → state `recording`. Visual: pulsing red icon, elapsed counter `0:04`.
- Tap `recording` → `recorder.stop()` (triggers `ondataavailable`) → blob from chunks → state `uploading` → POST `/api/v1/transcribe` via `lib/transcribe-api.ts` → on success, call `onTranscribed(...)` → state `idle`. On error, toast → state `idle` (audio blob is held in closure for one retry if we add that polish later).
- 60s timer fires → `recorder.stop()` + toast "max length reached".
- `requesting` deny → state `denied` → one-time toast "Microphone access denied — check browser settings" → next tap reruns the prompt.

Always release MediaStream tracks on stop. Always revoke object URLs.

### `lib/transcribe-api.ts` (new)

```ts
export async function transcribe(
  blob: Blob,
  opts?: { language?: string; signal?: AbortSignal }
): Promise<{ transcript: string; language?: string; durationMs?: number }>
```

Uses existing fetch/proxy pattern (`tutorbot-web/proxy.ts`). `AbortSignal` lets MicButton cancel an in-flight upload on unmount.

### `lib/unified-ws.ts` (modified)

Extend `sendMessage` to accept optional `attachments: AttachmentWire[]`:

```ts
type AttachmentWire = {
  type: 'image' | 'audio'
  filename: string
  mime_type: string           // snake_case to match backend Python
  base64: string
}
```

Existing call-sites pass undefined. New composer passes the array. No schema changes elsewhere.

### i18n keys (`tutorbot-web/locales/{en,zh}/app.json`)

```
composer.attach
composer.attachImage
composer.recordVoice
composer.stopRecording
composer.recordingTooLong
composer.transcribing
composer.transcribeFailed
composer.noSpeechDetected
composer.micDenied
composer.imageTooLarge
composer.imageWrongType
```

## Error handling

| Failure | Where caught | User-visible result |
|---|---|---|
| Browser denies mic permission | `MicButton` | Toast: `composer.micDenied`. Button stays interactive so a re-tap reruns the prompt. |
| `MediaRecorder` not supported | `MicButton` mount-time check | Mic button hidden. Composer otherwise works. |
| Audio blob > `STT_MAX_BYTES` | `transcribe.py` returns 413 | Toast: `composer.recordingTooLong`. |
| Unsupported audio MIME | `transcribe.py` returns 415 | Toast: `composer.transcribeFailed`. Should not occur in practice (frontend uses a curated MIME list). |
| STT provider 5xx / timeout | `transcribe.py` returns 502 | Toast: `composer.transcribeFailed`. |
| STT returns empty string | provider | Treated as success-with-empty. Composer not auto-filled. Toast: `composer.noSpeechDetected`. |
| Image > 10 MB or wrong MIME | `AttachmentPicker` | Inline toast (`composer.imageTooLarge` / `composer.imageWrongType`); attachment not added. |
| LLM doesn't support audio | `multimodal.py` silently drops audio | No error. Transcript text already in message; model answers from text. (Intended fallback, not an error.) |
| LLM doesn't support vision | `multimodal.py` strips images, sets `images_stripped=True` | Existing warning event reused. |
| WS reconnects mid-recording | `MicButton` agnostic; existing reconnect handles send | Recording survives; send may delay. |
| User closes tab during recording | Browser tears down MediaStream | Lost recording, no backend state to clean up. |
| Double-tap mic during `uploading` | `MicButton` state machine rejects taps outside `idle`/`recording` | No double-recording possible. |

## Testing strategy

### Python (pytest, fits existing `tests/` layout)

- `tests/services/stt/test_openai_whisper_provider.py` — mock `AsyncOpenAI`. Verify MIME→extension map, env-var fallback chain (`STT_API_KEY`→`LLM_API_KEY`, `STT_HOST`→`LLM_HOST`), `verbose_json` parsing, `STTResult` mapping.
- `tests/services/stt/test_registry.py` — register/get round-trip; unknown provider raises `ConfigurationError`; env-var selection.
- `tests/services/llm/test_capabilities_audio.py` — `supports_audio()` matrix: known true, known false, version-suffixed names, unknown bindings, `None` model.
- `tests/services/llm/test_multimodal_audio.py` — extends existing multimodal tests. Audio injection on capable model; silent drop on incapable model; `audio_dropped` counter; coexistence with image attachments in same message; OpenAI vs Gemini part shape.
- `tests/api/test_transcribe_router.py` — multipart happy path (mocked provider); 413 on oversize; 415 on bad MIME; 502 on provider error; language passthrough.
- `tests/tutorbot/test_context_media.py` — `build_user_message_with_media()` produces correct content array for image-only, audio-only, mixed, and no-media cases.

### Integration (gated)

- `tests/api/test_transcribe_router_real_openai.py` — guarded by `STT_API_KEY` env, marked `@pytest.mark.skipif`. Sends a fixture audio clip, asserts non-empty transcript. Lives outside the CI smoke set listed in CLAUDE.md.

### Frontend (Node)

None in v1 — `tutorbot-web/` has no test runner today. Add test infrastructure in a follow-up. For v1, rely on the manual smoke checklist below.

### Manual smoke checklist

1. Record voice on Chrome → transcript appears → edit → send → bot acknowledges spoken content.
2. Same on Safari (validates MediaRecorder mimeType fallback to mp4).
3. Deny mic permission in browser → button shows denied state, no crash.
4. Record > 60s → forced stop fires with toast.
5. Paste image from clipboard → chip appears → send → bot describes image.
6. Drag-drop image → chip appears.
7. Image + voice in same message → bot's reply references both.
8. Switch model from `gpt-4o` (vision + audio) to a text-only local model → image-stripped warning shows; audio silently dropped; behavior consistent.
9. Switch to `gpt-4o-audio-preview` → mic recording → confirm both audio and transcript reach the model (verify via server log: `audio_dropped=0`).

## Security considerations

- **Server-side MIME validation** in `transcribe.py` is the source of truth. Frontend `accept=""` is a UI hint, not a security boundary.
- **Size limit** enforced in the router before passing bytes to the provider — prevents OOM on a 500MB upload.
- **No audio persistence in v1** means zero storage-side concerns. When Phase 2 adds `attachment_store` for audio, follow the existing `_safe_join` pattern in `attachment_store.py`.
- **SVG XSS** — `AttachmentPicker` rejects SVGs containing `<script`. (Backend renderer should also sanitize; pre-existing concern beyond this spec's scope.)
- **CORS / auth** — `/api/v1/transcribe` inherits whatever auth context `unified_ws.py` and other API routes use today. Verify against `api/main.py` middleware stack during implementation. No new exposure surface introduced.
- **PII** — voice is biometric data. The user-facing settings should grow a privacy note (text task, no code change required for v1).

## File map summary

### New files

```
deeptutor/services/stt/__init__.py
deeptutor/services/stt/base.py
deeptutor/services/stt/provider_registry.py
deeptutor/services/stt/providers/__init__.py
deeptutor/services/stt/providers/openai_whisper.py
deeptutor/api/routers/transcribe.py
tests/services/stt/test_openai_whisper_provider.py
tests/services/stt/test_registry.py
tests/services/llm/test_capabilities_audio.py
tests/services/llm/test_multimodal_audio.py
tests/api/test_transcribe_router.py
tests/tutorbot/test_context_media.py
tutorbot-web/components/tutorbot/chat/Composer.tsx
tutorbot-web/components/tutorbot/chat/AttachmentChipRow.tsx
tutorbot-web/components/tutorbot/chat/AttachmentPicker.tsx
tutorbot-web/components/tutorbot/chat/MicButton.tsx
tutorbot-web/lib/transcribe-api.ts
```

### Modified files

```
deeptutor/api/main.py                              # register transcribe router
deeptutor/services/llm/capabilities.py             # supports_audio + _AUDIO_INPUT_MODELS
deeptutor/services/llm/multimodal.py               # audio parts + _inject_audio
deeptutor/tutorbot/agent/context.py                # rename + delegate to multimodal
deeptutor/tutorbot/agent/tools/message.py          # confirm audio MIME accepted (verify)
deeptutor/tutorbot/agent/loop.py                   # audit existing image filter for audio (verify)
.env.example                                       # new STT_* env vars
tutorbot-web/components/tutorbot/chat/BotChatView.tsx  # delegate to Composer
tutorbot-web/lib/unified-ws.ts                     # sendMessage accepts attachments
tutorbot-web/locales/en/app.json                   # composer.* keys
tutorbot-web/locales/zh/app.json                   # composer.* keys
```

## Open questions for the implementation plan

1. **Gemini audio part shape** — confirm against the actual converter in `services/llm/provider_core/` rather than guessing. Implementer should read the existing Gemini multimodal code path before writing `_build_gemini_audio_part`.
2. **Auth on `/api/v1/transcribe`** — confirm what middleware applies and whether the multi-user package's grant system should gate this. If yes, this is the first new API endpoint added since multi-user landed; verify the grant attaches correctly.
3. **Audit `tutorbot/agent/loop.py:1275`** — the existing image-filter behavior should be checked against audio attachments before implementation; the design assumes audio is exempt but this should be verified.
