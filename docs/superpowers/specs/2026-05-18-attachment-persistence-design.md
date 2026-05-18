# Attachment Persistence (Phase 2) — Design

**Date:** 2026-05-18
**Branch:** chatV2
**Frontend:** `tutorbot-web/`
**Status:** Approved for implementation planning
**Predecessor spec:** `docs/superpowers/specs/2026-05-18-multimodal-input-design.md` (Phase 1)

## Problem

Phase 1 added image + voice attachments on the TutorBot chat path. Those attachments live only in the current browser session — on page reload, the user bubbles show no image (the `loop.py:1331` filter replaces inline `data:image/...` parts with `[image]` text before persisting to session JSONL, to keep history compact).

Phase 2 makes attachments survive page reload by persisting their bytes through the existing `AttachmentStore` and storing URL refs in session history, exactly mirroring the pattern the legacy `web/` chat path already uses at `turn_runtime.py:752`.

Phase 2 also closes a small pre-existing gap surfaced by this work: `services/llm/multimodal._inject_audio` currently skips URL-only audio attachments (only `_inject_images` handles the URL→bytes resolution today).

## Decisions

| ID | Decision | Notes |
|----|----------|-------|
| **D-Scope** | Scope is image + audio attachments on the TutorBot path. | The Phase 1 wire format is unchanged; this work is purely about durability across reload. |
| **D-Store** | Reuse the existing `LocalDiskAttachmentStore` at `data/user/workspace/chat/attachments/<sid>/<aid>_<name>`. | Single storage backend across the whole app. No per-bot path variant; deferred until multi-tenant deployment surfaces a real need. |
| **D-Timing** | Persist on receive, *before* the multimodal layer runs (Approach A from brainstorming). | Mirrors `turn_runtime.py:752`. Reuses `multimodal._resolve_local_attachment_url`. Bytes only live in memory at the WS-receive boundary; everything downstream operates on URL refs. |
| **D-OldHistory** | Existing `[image]` text placeholders in pre-Phase 2 history stay untouched. | No migration. The original bytes were never persisted, so there is nothing to recover. Only NEW turns get URL-backed persistence. |
| **D-Failure** | Persistence failure (disk full, decode error) is logged at WARNING and the attachment keeps its in-memory `base64`. | LLM call still works; only history durability is lost for that turn. Graceful degradation. |
| **D-Sessions** | `attachment_store` session_id is the bare suffix of the TutorBot canonical key (`bot:<bot_id>:s:<sid>` → `<sid>`). | Yields paths identical in shape to the legacy chat path: `data/user/workspace/chat/attachments/<sid>/...`. |
| **D-Auth** | `/api/attachments/` keeps its current auth posture (session-id as ACL boundary, no FastAPI dependency). | Phase 2 does not change the trust model. Signed URLs remain a future-tense concern noted in `attachment_store.py`. |

### Deliberately out of scope

- Per-bot attachment path under `data/tutorbot/<bot_id>/`.
- Multi-user signed URLs.
- Backfill of pre-Phase 2 `[image]` placeholders.
- S3 / MinIO / cloud storage backends (the `AttachmentStore` Protocol already accommodates them — adding one is a separate task).
- `web/` (legacy) chat path — it already does this via `turn_runtime.py:752`.
- Hygiene pass to clean orphaned files from failed turns (`delete_session` exists; can be wired into session-deletion later).

## Architecture

```
tutorbot-web sends WS frame:
  { content: "describe this",
    attachments: [{type:"image", base64:"...", mime_type:"image/png", filename:"x.png"}] }
              ↓
api/routers/tutorbot.py WS handler (unchanged)
              ↓
mgr.send_message(bot_id, content, attachments=...)
              ↓
agent_loop.process_direct → _process_message
   │
   ├─ NEW: persist_attachments(<session_id>, canonical_attachments)
   │    • Decode base64 → bytes
   │    • attachment_store.put(...) → "/api/attachments/<sid>/<aid>/<name>"
   │    • Mutate Attachment in place: url=<url>, base64=""
   │    • On failure: log WARNING, leave base64, continue
   │
   ├─ build_user_message_with_media(...)  (unchanged)
   │    multimodal.prepare_multimodal_messages now sees attachments with
   │    .url set and .base64 empty; _resolve_local_attachment_url reads
   │    bytes from disk only when injection is required.
   │
   ├─ LLM call (unchanged)
   │
   └─ _save_turn  (unchanged)
        Session JSONL now contains user message content with image_url
        parts that reference /api/attachments/... URLs. The existing
        [image] filter at loop.py:1331 becomes a defensive no-op for
        the new path (it only fires for data:image/... URLs).
              ↓
GET /api/v1/tutorbot/{bot_id}/sessions/{sid}/history
        Extended serializer scans each user turn's content for
        image_url parts whose URL starts with /api/attachments/ and
        emits a top-level `attachments` field on the entry.
              ↓
BotChatView's history-restore code parses attachments into
BotChatTurn.attachments. The bubble renderer's fallback chain:
   src = att.previewUrl ?? att.url ?? base64-data-URL
        ↓ <img src="/api/attachments/<sid>/<aid>/<name>">
        ↓ browser GETs the URL → existing attachments router serves bytes
        ↓ image renders in old turns after reload ✓
```

### Key invariant

After `persist_attachments` runs successfully, every persisted attachment has `url` set and `base64=""`. Inline base64 only exists transiently at the WS-receive boundary. Multimodal layer, save_turn, history endpoint, frontend — all downstream stages operate on URL refs.

## Data flow

**Flow A — Fresh send (new turn)**

1. Composer holds `Attachment{base64, previewUrl=blob:..., url=undefined}`. User clicks Send.
2. `BotChatView.handleSend` stores the attachment on a new `BotChatTurn` (with `previewUrl` for instant render this session — unchanged) and ships the wire frame `{content, attachments:[{type, base64, mime_type, filename}]}` over WS.
3. Backend's `_process_message` builds `canonical_attachments` then calls `persist_attachments(session_id, canonical_attachments)`. After this, each persisted attachment has `url="/api/attachments/<sid>/<aid>/<name>"` and `base64=""`. File exists on disk.
4. `build_user_message_with_media` runs; multimodal reads `.url` and resolves to bytes when vision/audio is supported. LLM call proceeds normally.
5. `_save_turn` writes JSONL. The user message's content is a content-parts list where image_url parts reference the URL form (not data:). `[image]` filter doesn't fire.

**Flow B — Page reload (history restore)**

1. Frontend boots and GETs `/api/v1/tutorbot/{bot_id}/sessions/{sid}/history`.
2. Backend serializer enriches each user turn that has URL-form `image_url` parts with a top-level `attachments` field:
   ```json
   { "role": "user",
     "content": "describe this",
     "attachments": [
       {"type":"image", "url":"/api/attachments/sid/aid/x.png",
        "mime_type":"image/png", "filename":"x.png"}
     ] }
   ```
3. `BotChatView`'s history-restore code parses `attachments` into `BotChatTurn.attachments`.
4. Bubble renderer's fallback chain:
   ```ts
   const src =
     att.previewUrl ??         // fresh sends this session
     att.url ??                // restored from history
     (att.base64 ? `data:${att.mimeType};base64,${att.base64}` : undefined)
   ```
5. `<img src="/api/attachments/...">` triggers a GET → existing attachments router serves the bytes → image renders.

**Flow C — Multimodal boundary (unchanged)**

The persistence step happens *before* multimodal gating, so the multimodal layer sees the same attachment shape regardless of when bytes were uploaded. `supports_vision/supports_audio` checks decide whether to inject; `_resolve_local_attachment_url` handles the URL→bytes round-trip transparently.

## Components

### New: `deeptutor/tutorbot/agent/attachment_persistence.py`

One module, ~40 LOC, single responsibility. Lives in `tutorbot/agent/` (not `services/`) because it encodes TutorBot's policy. The legacy chat path has its own inline equivalent in `turn_runtime.py:752`; we don't share code because the call shapes differ.

```python
"""Persist canonical Attachment objects to AttachmentStore in place.

Called from the agent loop before the multimodal/LLM step so the saved
session JSONL stores compact URL refs instead of inline base64.
"""

import base64 as _b64
import logging
import uuid

from deeptutor.core.context import Attachment
from deeptutor.services.storage import get_attachment_store

logger = logging.getLogger(__name__)


async def persist_attachments(
    session_id: str,
    attachments: list[Attachment],
) -> None:
    """Persist any attachment that has base64 bytes but no url.

    Mutates each Attachment: sets ``.url`` to the public URL and clears
    ``.base64`` once bytes are safely on disk. On failure, leaves ``base64``
    intact so the LLM call can still proceed from the in-memory payload —
    the attachment just won't survive a page reload.
    """
    if not attachments:
        return
    store = get_attachment_store()
    for att in attachments:
        if att.url:
            continue  # already hosted
        if not att.base64:
            continue
        if not att.id:
            att.id = uuid.uuid4().hex[:12]
        try:
            raw = _b64.b64decode(att.base64, validate=False)
        except Exception as exc:
            logger.warning(
                "tutorbot: skipping attachment persistence for %r: bad base64 (%s)",
                att.filename, exc,
            )
            continue
        try:
            att.url = await store.put(
                session_id=session_id,
                attachment_id=att.id,
                filename=att.filename or "file",
                data=raw,
                mime_type=att.mime_type or "",
            )
            att.base64 = ""  # bytes live on disk; multimodal will read
                             # via _resolve_local_attachment_url
        except Exception as exc:
            logger.warning(
                "tutorbot: attachment store rejected %r: %s — keeping base64",
                att.filename, exc,
            )
```

### Modified: `deeptutor/tutorbot/agent/loop.py`

Two changes:

1. **Two-line addition** in `_process_message` right after `canonical_attachments` is built:

```python
canonical_attachments = [Attachment(...) for a in msg.attachments]
# NEW:
from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments
await persist_attachments(_session_id_from_key(session_key), canonical_attachments)
# Existing logger.info + build_user_message_with_media...
```

2. **Module-level helper:**

```python
def _session_id_from_key(session_key: str) -> str:
    """Extract the bare session-id from canonical key 'bot:<bot_id>:s:<sid>'."""
    return session_key.split(":s:")[-1]
```

The existing `[image]` filter at `loop.py:1331-1334` stays as a defensive net (it only fires when content arrives with `data:image/...` URLs, which the new path no longer produces). No removal needed; a one-line comment notes the new lifecycle.

### Modified: `deeptutor/services/llm/multimodal.py`

Extend `_inject_audio` to mirror `_inject_images`' URL-only handling. Currently:

```python
def _inject_audio(messages, user_idx, audio_attachments):
    ...
    for att in audio_attachments:
        b64 = getattr(att, "base64", "") or ""
        if not b64:
            continue
        ...
```

New behavior: if `base64` is empty but `url` is set and resolvable via `_resolve_local_attachment_url`, use the resolved bytes. Same pattern as `_inject_images` (lines 252-264).

Add a parallel `audio_dropped` counter increment when URL resolution fails — this is the audio analog of the existing `url_images_dropped`.

### Modified: `deeptutor/api/routers/tutorbot.py:get_session_history` (and the session-scoped variant)

Add a small enrichment pass over each user-role turn. New helper:

```python
_ATT_URL_PREFIX = "/api/attachments/"

def _extract_attachments_from_content(content) -> list[dict] | None:
    """Emit a flat attachments list for URL-form image_url / input_audio
    parts on a user message. Returns None if content has no qualifying
    attachment parts."""
    if not isinstance(content, list):
        return None
    out: list[dict] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith(_ATT_URL_PREFIX):
                out.append({
                    "type": "image",
                    "url": url,
                    "mime_type": _infer_mime_from_url(url),
                    "filename": url.rsplit("/", 1)[-1],
                })
        elif ptype == "input_audio":
            # Audio is base64-inline at injection time and not URL-form
            # today. When Phase 2.1 wires URL-based audio injection, add
            # the parallel branch here.
            pass
    return out or None


def _infer_mime_from_url(url: str) -> str:
    import mimetypes
    return mimetypes.guess_type(url.rsplit("/", 1)[-1])[0] or ""
```

Applied per user turn during history serialization. Backward-compatible: turns without `image_url` parts get no `attachments` field.

Cleanest implementation puts the helper in `routers/tutorbot.py` near the existing endpoint. If `mgr.get_bot_history` is the right layer, push it down there instead — implementer decides during the plan.

### Modified: `tutorbot-web/lib/bot-ws.ts`

`BotChatTurnAttachment` gains an optional `url?: string`:

```ts
export type BotChatTurnAttachment = {
  type: "image" | "audio";
  filename: string;
  mimeType: string;
  base64?: string;
  previewUrl?: string;  // fresh-send only, blob: URL
  url?: string;         // NEW: persisted attachment URL from history
};
```

### Modified: `tutorbot-web/components/tutorbot/chat/BotChatView.tsx`

Two changes:

1. **History restore** (around the existing fetch at ~line 71): read each turn's `attachments` field and populate `BotChatTurn.attachments`. Map snake_case → camelCase.

2. **Bubble renderer**: extend the fallback chain to include `url`:

```tsx
const src =
  att.previewUrl ??        // fresh sends this session
  att.url ??               // restored from history
  (att.base64 ? `data:${att.mimeType};base64,${att.base64}` : undefined)
```

### Unchanged

- `tutorbot-web/components/tutorbot/chat/Composer.tsx` — Composer still passes full `Attachment{base64, previewUrl}` to BotChatView. The previewUrl-vs-url distinction is purely a turn-level concern.
- `tutorbot-web/lib/agent-chat-types.ts` — `Attachment` and `AttachmentWire` types stay the same; the wire format isn't extended.
- `deeptutor/services/storage/attachment_store.py` — already supports the pattern; no changes.

## Error handling

| Failure | Where caught | User-visible result |
|---|---|---|
| `attachment_store.put` raises (disk full, permission, path-escape) | `persist_attachments` `except Exception` | Logged at WARNING with filename. Attachment keeps `base64`, `url` stays empty. LLM call proceeds normally. On reload, that turn's image won't appear (no URL persisted). No user-facing error — graceful degradation. |
| `base64.b64decode` raises (corrupt payload) | `persist_attachments` | Logged at WARNING. Attachment skipped. LLM call may also fail later when multimodal tries to inject — that's the LLM's error path, separate. |
| Storage backend isn't `LocalDiskAttachmentStore` (future S3 backend) | `attachments` router already returns 501 | Frontend shows broken image for restored turns. Acceptable — `attachment_store.py` already comments this branch needs a signed-URL redirect path before remote backends ship. |
| History entry has `image_url` part with a URL that no longer exists on disk (file deleted, session pruned) | `attachments` router returns 404 | Frontend shows broken image placeholder. Matches current browser behavior for any missing image. |
| Multimodal layer can't resolve URL → bytes for vision injection | `_inject_images` / `_inject_audio` falls through to drop | Counter `url_images_dropped` already exists; logged. LLM gets text-only. Same as Phase 1 behavior. |
| Concurrent persistence collision (same `attachment_id` in same session) | `attachment_store._safe_join` overwrites — same content, same URL | No conflict. UUIDs make this effectively impossible anyway. |
| Old chat session (pre-Phase 2) has `[image]` text in saved content | History serializer's `_extract_attachments_from_content` returns None for text content | Old turns render as today — text bubble with `[image]` placeholder. Per D-OldHistory, no migration. |

## Testing strategy

### Python (pytest)

**`tests/tutorbot/test_attachment_persistence.py` — new, ~6 tests**

- `test_persist_round_trip` — base64 in, URL out, base64 cleared, file on disk
- `test_already_hosted_skipped` — attachment with pre-existing url isn't re-uploaded
- `test_no_base64_no_op` — empty base64 → no-op, no warning
- `test_assigns_id_when_missing` — uuid generated when att.id is empty
- `test_store_failure_keeps_base64` — patched store raises → base64 preserved, url empty, no exception bubbles
- `test_invalid_base64_logged_and_skipped` — bad input → warning, attachment marked skipped, no crash

**`tests/tutorbot/test_loop_persistence_integration.py` — new, ~3 tests**

- `test_process_message_persists_before_multimodal` — mock multimodal, verify attachments arrive with `url` set and `base64=""`
- `test_session_id_extracted_from_canonical_key` — `bot:abc:s:s_default` → `s_default`
- `test_persist_failure_does_not_block_llm_call` — patched store raises, verify multimodal still called with base64-bearing attachment

**`tests/services/llm/test_multimodal_audio.py` — extend with one new test**

- `test_audio_url_resolved_to_base64_for_supported_model` — audio attachment with url+empty base64, audio-capable model, verify resolved bytes injected. Closes the URL-resolution gap in `_inject_audio`.

**`tests/api/test_tutorbot_history_attachments.py` — new, ~3 tests**

- `test_history_user_turn_with_image_url_emits_attachments_field` — saved JSONL with `image_url` URL part → response has top-level `attachments`
- `test_history_user_turn_with_only_text_omits_attachments` — backward compat
- `test_history_image_url_with_data_scheme_ignored` — defensive: `data:image/...` URL doesn't become an attachment entry (only `/api/attachments/...` URLs do)

**Existing `tests/services/llm/test_multimodal.py`** — verify regression: `_inject_images` still resolves URL-only attachments via `_resolve_local_attachment_url`. Likely already covered; add a parametrized case if not.

### Frontend (Node)

Still no test runner in `tutorbot-web/`. Manual smoke only.

### Manual smoke checklist

1. Send an image to a TutorBot. Confirm a row in `data/user/workspace/chat/attachments/<sid>/...` and that the saved session JSONL contains an `image_url` part with a `/api/attachments/...` URL (not `[image]` text and not base64).
2. **Reload the page** — the image must render in the user bubble. This is Phase 2's main success criterion.
3. With a vision-capable model: verify the bot describes the image (multimodal URL→bytes resolution still works after persistence).
4. With DeepSeek (or any non-vision model): bot replies without crash; URL is still persisted (history goal met) even though LLM didn't see the bytes.
5. Old chat sessions (with `[image]` placeholders from pre-Phase 2) still load and render their text correctly — no migration regression.
6. Voice path: send a voice note, reload page. Audio chip should reappear with a playable `<audio>` element wired to the persisted URL.
7. Simulate disk failure: set `CHAT_ATTACHMENT_DIR=/nonexistent`, send an image, verify (a) warning in backend log, (b) LLM call still completes, (c) on reload the user bubble shows no image.

## Security considerations

- **Same posture as today.** `/api/attachments/<sid>/<aid>/<filename>` already exists with session-id as the ACL boundary (per its docstring). Phase 2 does not change the trust model; multi-user signed URLs remain a future concern.
- **Path safety**: reuses `LocalDiskAttachmentStore._safe_join` — already defends against `../` escapes and symlink attacks. No new attack surface.
- **Storage growth**: Phase 2 trades Phase 1's zero-persistence for image durability. Files now sit on disk under `data/user/workspace/chat/attachments/`. The store has `delete_session` available; wire it into session-deletion paths in a future hygiene task (out of scope for this spec).

## File map summary

### New files

```
deeptutor/tutorbot/agent/attachment_persistence.py
tests/tutorbot/test_attachment_persistence.py
tests/tutorbot/test_loop_persistence_integration.py
tests/api/test_tutorbot_history_attachments.py
```

### Modified files

```
deeptutor/tutorbot/agent/loop.py                         # call persist_attachments + _session_id_from_key helper
deeptutor/services/llm/multimodal.py                     # _inject_audio URL resolution + audio_dropped counter
deeptutor/api/routers/tutorbot.py                        # history serializer enriches user turns with attachments[]
tests/services/llm/test_multimodal_audio.py              # +1 test for audio URL resolution
tutorbot-web/lib/bot-ws.ts                               # BotChatTurnAttachment.url?: string
tutorbot-web/components/tutorbot/chat/BotChatView.tsx    # history restore + bubble renderer fallback chain
```

## Open question for the implementation plan

1. **History serializer layering** — does the enrichment helper live in `routers/tutorbot.py` next to the endpoint, or push down into `services/tutorbot/manager.py:get_bot_history` so all callers benefit? Implementer decides while in the code.
