# Sidebar Session Tree — Design

**Date:** 2026-05-17
**Branch:** chatV2
**Frontend:** `tutorbot-web/` (the chatV2 frontend)
**Status:** Approved for implementation planning

## Problem

Today every TutorBot has a single continuous conversation, persisted as one JSONL file keyed `bot:<bot_id>`. The history is loaded by `GET /api/v1/tutorbot/{bot_id}/history` and exists nowhere in the UI — the sidebar shows top-level nav (TutorBot, Knowledge, Souls) but no history. Users cannot see, switch between, or even discover past tutoring conversations.

The goal is a tree in the sidebar:

```
📚 辅导机器人
   🤖 数学老师
      💬 二元一次方程的解法
      💬 一元二次方程的判别式
   🤖 化学助教
      💬 氧化还原反应的概念知识
```

Each leaf is a session with a lesson-like title (e.g. "二元一次方程的解法").

## Decisions

These were settled during brainstorming and are binding for the implementation plan.

| ID | Decision | Notes |
|----|----------|-------|
| **B** | One session per lesson plan. | A bot may hold many sessions over time. The existing `LessonPlan.topic` becomes the session title — no extra LLM call. |
| **B1** | Pre-lesson chat lives in a per-bot default session. | When `plan_lesson` runs in the default session, it is *promoted* (renamed to the plan's topic) and a fresh empty default takes its place. |
| **R1** | Clicking an old session *resumes* it. | Full message history and lesson-plan state are restored. The bot can replan inside a resumed session. |
| **M3** | "+ New chat" enabled only when the default session has ≥ 1 user message. | Prevents two empty drafts side-by-side. |
| **G1** | Migration collapses each existing per-bot JSONL into one archived session. | Title: "之前的对话". No attempt to chunk by historical lesson-plan boundaries. |
| **Backend approach** | Multi-key `SessionManager` (Approach 1). | Reuse the existing key/value session store. SQLite indexing deferred until needed. |

## Architecture

### Data model

`SessionManager` keys generalize from `bot:<bot_id>` to `bot:<bot_id>:s:<session_id>`. `session_id` is a short ULID-ish string (`s_01HXXXX...`). The well-known id `s_default` is used *only* at bootstrap (the very first default session a bot ever gets); subsequent defaults — allocated by `promote_default` after every promotion — are ULID-based like any other session. **Session ids are immutable for the life of the session**, so URL bookmarks to `/tutorbot/{bot}/chat/{sid}` stay valid even after that session is promoted from `default` to `active`. Clients identify "the current default" by reading `status="default"` from the session list, not by hard-coding `s_default`. Files live at `<bot_workspace>/sessions/bot_<bot_id>_s_<session_id>.jsonl` (`_get_session_path` already slugifies colons).

Each session's `metadata` dict gains four fields (all optional, backward-compatible with existing on-disk JSONL):

```python
title:        str | None    # "二元一次方程的解法" once promoted; None for empty default
title_source: str | None    # "lesson_plan" | "manual" | "auto" (reserved) | None
status:       str           # "default" | "active" | "completed" | "archived"
lesson_plan:  dict | None   # existing field, unchanged
```

Status semantics:

- `default` — exactly one session per bot has this status. Holds pre-lesson chat.
- `active` — promoted via `plan_lesson`; the plan is still in progress.
- `completed` — either the lesson plan finished (last step done), or M3 promoted the default manually without a topic.
- `archived` — created by the G1 migration; not user-deletable in v1.

### Session lifecycle

1. **Bootstrap.** On WS connect or `GET /sessions`, if no session under `bot:<id>:s:*` has `status="default"`, the SessionManager creates one with id `s_default` (empty title, no lesson plan).
2. **Pre-lesson chat.** All messages from a freshly-opened bot land in the default session.
3. **Lesson promotion (auto).** When `plan_lesson` runs **in the default session**:
   - `title ← plan.topic`, `title_source ← "lesson_plan"`, `status ← "active"`.
   - A new session with id `s_<ulid>`, empty title, and `status="default"` is created and becomes the new default.
   - A `session_promoted` event is pushed over the WS so the open browser can patch its sidebar without polling.
4. **Lesson promotion inside an already-named session.** When `plan_lesson` runs in a non-default session (R1 resume case), the existing `lesson_plan` is overwritten and `title` is updated to the new topic. No new session is created — the user stays where they are.
5. **Manual new chat (M3).** `POST /sessions`:
   - If the current default has 0 messages → `409 { existing_default_id }`. UI navigates to the existing default; no new session created.
   - If ≥ 1 message → promotes the current default with `title="", title_source="manual", status="completed"`, then creates a fresh default and returns its id.
6. **Lesson completion.** When the lesson plan's last step transitions to `done`, the session's `status ← "completed"`. Resuming it via R1 keeps it `completed` until another `plan_lesson` flips it back to `active`.

### Migration (G1)

Migration runs **lazily, per bot**, at `SessionManager` layer — not a one-shot script. The first time `get_or_create` is called with a new-style key for a bot whose workspace still contains a legacy `bot_<id>.jsonl`, the manager:

1. Reads the legacy JSONL.
2. Allocates a new session id `s_<ulid>` and writes the messages to `bot_<id>_s_<sid>.jsonl`.
3. Sets metadata: `status="archived"`, `title="之前的对话"` (the UI renders this through the i18n key `session.legacy_title`; the stored title is the zh-CN default for users on older clients), `title_source="auto"`. Any lesson plan in legacy metadata is copied verbatim, but the session stays archived (we don't revive an old lesson).
4. Creates a fresh `s_default` empty session.
5. Renames the legacy file to `bot_<id>.jsonl.migrated` as a one-release safety net.

Idempotency: the `.migrated` suffix is the migration marker. If both `bot_<id>.jsonl` and `bot_<id>.jsonl.migrated` exist (operator restored the legacy file by accident), the manager logs a warning and refuses to migrate again — operator must resolve.

On malformed legacy JSONL, `SessionManager._load` already catches and logs. The legacy file is not renamed, so the bot has no sessions visible until operator intervenes — preferable to silently dropping history.

### Promotion wiring inside `plan_lesson`

The `plan_lesson` tool in `deeptutor/tutorbot/agent/tools/lesson.py` currently calls `lesson.store.save(session, plan)`. We extend that path:

- After `save`, if `session.metadata.status == "default"` (or unset, treated as default), call `SessionManager.promote_default(session)`. This is the only path that allocates a new default.
- Emit a `SessionPromotedEvent` on the bot's notify queue (the queue already exists for proactive messages). The WS handler picks it up and sends the wire event below.

Concurrent promotion is bounded by the SessionManager's in-memory `_cache` (per-process singleton): two racing `plan_lesson` calls observe the same session object, the second sees `status != "default"` and falls through into the rule-4 "replan inside named session" branch.

## API

All new endpoints are nested under `/api/v1/tutorbot/{bot_id}`.

### Listing & creating

```
GET    /sessions
       → 200 [{ id, title, title_source, status, updated_at, lesson_plan_brief }]
         Ordered: default first, then by updated_at desc.
         lesson_plan_brief = { topic, current_step_id, total_steps, done_steps } | null

POST   /sessions
       Body: {}     (server allocates id, marks status=default)
       → 201 { id, title: "", status: "default", ... }
       → 409 { existing_default_id }  when current default has 0 messages
```

### Per-session ops

```
GET    /sessions/{sid}/history?limit=100
       → 200 [{ role, content }]

PATCH  /sessions/{sid}    (defined; v1 implementation deferred)
       Body: { title?: str, status?: "completed"|"archived" }
       → 200 { ...updated session record }

DELETE /sessions/{sid}    (defined; v1 implementation deferred)
       → 204
       → 409 if sid is the current default
       (Hard-deletes the JSONL file.)

WS     /sessions/{sid}/ws
       Same protocol as today's /ws (content, thinking, lesson_plan, done, error)
       Auto-starts the bot if not running.
```

### Tree-level convenience

```
GET    /api/v1/tutorbot/tree
       → 200 [{ bot_id, name, running, sessions: [<as above>] }]
```

### Server-pushed events (existing WS protocol)

When promotion fires, the WS pushes:

```json
{
  "type": "session_promoted",
  "promoted":     { "id": "...", "title": "...", "title_source": "lesson_plan", "lesson_plan_brief": {...} },
  "new_default":  { "id": "...", "title": "",    "status": "default" }
}
```

The sidebar listens on the active chat's WS (already open) and patches its tree state. No polling.

### Deprecation path

- `GET /api/v1/tutorbot/{bot_id}/history` → keeps working; returns the current default session's history. Adds a deprecation header.
- `WS /api/v1/tutorbot/{bot_id}/ws` → keeps working; binds to the current default session. Logs a deprecation warning server-side.

The deprecated routes can be removed once the legacy `web/` frontend is retired or moved over. `tutorbot-web/` switches to the session-scoped routes as part of this work.

## Frontend

### Routes

```
/tutorbot/[botId]/chat                  → resolves the current default session, redirects
/tutorbot/[botId]/chat/[sessionId]      → new canonical route
```

The existing `BotChatPage` becomes a thin redirect: on mount it calls `GET /sessions`, finds the one with `status="default"`, and `router.replace`s to `/tutorbot/[botId]/chat/[sessionId]`. The real chat lives in a new `[sessionId]/page.tsx` route segment.

> The `tutorbot-web/` app uses a pre-release Next.js whose APIs differ from public docs. Implementers must consult `tutorbot-web/node_modules/next/dist/docs/` for current route-segment, dynamic-param, and redirect behavior before writing this layer (per `tutorbot-web/AGENTS.md`).

### Sidebar data flow

A new `SessionTreeContext` (in `tutorbot-web/context/`) owns the tree state:

```ts
{
  tree: { botId, name, running, sessions: SessionRow[] }[],
  expanded: Record<botId, boolean>,
  activeBotId: string | null,
  activeSessionId: string | null,
  refresh(): Promise<void>,
  toggleBot(botId): void,
  patchSession(botId, session): void,
  patchPromotion(botId, promoted, newDefault): void,
}
```

- `AppSidebar` consumes the context and renders the tree per the layout below.
- `refresh()` runs on mount and on bot-list-change events emitted by the bot manager.
- Bot-row expand state lives in `localStorage` keyed by botId.
- `BotChatView` calls `patchPromotion()` when its WS receives `{type: "session_promoted"}`.

### Sidebar layout

Anatomy of each session row:

| State | Visual | Behavior |
|-------|--------|----------|
| `default` (empty) | "新会话" with ＋ glyph, italic muted | Clicking navigates to it |
| `default` (non-empty) | "新会话" + ＋ button enabled on bot-row hover | Same as above; ＋ enables M3 new chat |
| `active` (current lesson) | Topic title + blue left rail + step progress `done_steps/total_steps` (e.g. `3/5`) | Active highlight; rail color from `--primary`. Hidden if `total_steps == 0` |
| `completed` | Topic title (muted) + "完成" badge | Resumable via R1 |
| `archived` (G1) | "之前的对话" + 📦 + "归档" badge | Resumable via R1, like completed |

Sidebar widens from 220→260px when sessions are visible. Active bot auto-expands on chat-page mount; others remember last expand state via `localStorage`. Long session lists scroll inside the sessions group; the bot row stays sticky at the top of its group.

Collapsed sidebar (60px) keeps only the top-level nav icons. The session tree is not shown when collapsed — clicking 📚 expands the sidebar back. No tooltip menu of sessions in collapsed mode (out of scope for v1).

### `BotChatView` changes

Currently it derives `botId` from the route and connects to `/api/v1/tutorbot/{botId}/ws`. It will also take `sessionId`, connect to `/api/v1/tutorbot/{botId}/sessions/{sid}/ws`, and load history from `/sessions/{sid}/history`. Sidebar's active highlight reads `activeSessionId` from the context, set whenever this view mounts.

`lib/bot-ws.ts`: `connectBotWS` gains a `sessionId` parameter; URL builder picks the session-scoped path.

### i18n keys

Five new keys, en + zh-CN:

- `sidebar.tutorbots` — "TutorBot" / "辅导机器人"
- `session.new_chat` — "New chat" / "新会话"
- `session.legacy_title` — "Previous chat" / "之前的对话"
- `session.completed_badge` — "Done" / "完成"
- `session.archived_badge` — "Archived" / "归档"

## Failure modes

| Scenario | Behavior |
|----------|----------|
| Promotion partially succeeds (default renamed but new default not created) | Next WS connect's bootstrap creates one. No data loss. |
| Migration JSONL is malformed | `SessionManager._load` catches and logs. Legacy file is *not* renamed, so the bot has no sessions until operator intervenes. |
| Concurrent `plan_lesson` (two racing turns) | SessionManager's in-memory cache ensures both see the same session object; second call sees `status != "default"` and uses the replan-in-place branch. |
| Two WS clients connect to the same session | Both receive `session_promoted` events. Patching is idempotent (keyed by session id). |
| `POST /sessions` while default has messages but client already opened a new session | Server returns 201 with a new id; client navigates. Old client still on the just-promoted session is fine — it now has a title. |

## Testing

### Backend (`pytest`)

Under `tests/services/session/`:
- `test_session_manager_multi_key.py` — round-trip create/save/load with `bot:<id>:s:<sid>` keys; idempotent `get_or_create`; `list_sessions` returns sessions sorted with default first.
- `test_session_promotion.py` — `promote_default` flips status/title, allocates a new default, emits the event. Replan in a non-default session updates title/plan in place; no new session.
- `test_session_migration.py` — legacy `bot_<id>.jsonl` becomes one `archived` session + a fresh empty `default`; rename to `.migrated` happens; running migration twice is a no-op; malformed legacy file leaves the original in place.

Under `tests/api/`:
- `test_tutorbot_sessions_api.py` — `GET /sessions`, `POST /sessions` (both create-new and 409-existing-default paths), `GET /sessions/{sid}/history`, WS `/sessions/{sid}/ws` happy path. Verify the `session_promoted` event is pushed when `plan_lesson` runs.
- Regression: existing `GET /history` and `WS /ws` continue to return data via the current default session.

### Frontend (Playwright)

Location: confirm against the actual Playwright suite in `tutorbot-web/` during implementation. (The `web/` legacy frontend has its own audit suite; `tutorbot-web/`'s is the relevant one here.)

- Sidebar renders 辅导机器人 → bot rows → session rows after login.
- Clicking a completed session navigates to `/tutorbot/{bot}/chat/{sid}`, history loads, sending a message appends to that session.
- Triggering `plan_lesson` in a default session renames it in the sidebar and inserts a new empty default without page reload.
- "+ New chat" is disabled when default is empty, enabled after one user message; clicking it after promotes the current default and navigates to the new one.
- Collapsed sidebar shows only top-level icons (no session tree).

### Manual smoke (Windows dev env)

- `python -m deeptutor.api.run_server` + `cd tutorbot-web && npm run dev`, log in, exercise the flows above.
- Verify a bot whose JSONL pre-dates migration shows one "之前的对话" (archived) row plus a fresh "新会话".

## Out of scope (v1)

- Session rename / delete UI (endpoints `PATCH` / `DELETE` are defined but not wired in v1).
- Collapsed-sidebar tooltip menu of sessions.
- Search across sessions.
- SQLite session index (Approach 2 in the brainstorm).
- Splitting historical per-bot JSONLs by lesson-plan boundaries during migration (G2 was rejected — current data only stores one plan per bot).
- Updating the legacy `web/` frontend. This work targets `tutorbot-web/` only.

## Open follow-ups (post-v1)

- Decide a retention policy for `.migrated` files after one release.
- When session count per bot grows large (e.g. > 50), revisit the SQLite index path — listing N files becomes the slow path.
- Cross-session memory: today `MEMORY.md` / `HISTORY.md` are per-bot consolidations that already carry across the single per-bot session. Under multi-session, they remain per-bot (working memory = per session, long-term memory = per bot). This is assumed but worth verifying once implementation starts.
