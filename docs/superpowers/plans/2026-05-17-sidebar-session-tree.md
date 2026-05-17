# Sidebar Session Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TutorBot conversation history visible in the sidebar as a tree (辅导机器人 → bot → sessions), with one session per lesson plan, auto-generated lesson titles, R1-resume, M3 manual new-chat rule, and lazy migration of existing per-bot JSONL files.

**Architecture:** Backend generalizes the `SessionManager` key from `bot:<bot_id>` to `bot:<bot_id>:s:<session_id>`. A `default` session per bot holds pre-lesson chat; calling `plan_lesson` *promotes* the default (sets title = `plan.topic`) and rolls a fresh empty default. New session-scoped REST/WS endpoints expose listing, history, and chat; existing endpoints stay backward-compatible. Frontend adds a `SessionTreeContext` consumed by `AppSidebar`, a new `[sessionId]` route segment, and updates `BotChatView` to bind to the chosen session.

**Tech Stack:** Python 3 / FastAPI / Pydantic / pytest. TypeScript / Next.js 16 (pre-release) / React 19 / react-i18next.

**Spec:** `docs/superpowers/specs/2026-05-17-sidebar-session-tree-design.md`. **Read it before starting.** It documents every decision (B / B1 / R1 / M3 / G1) and lifecycle rule referenced below.

**Pre-release Next.js warning:** `tutorbot-web/` uses a pre-release Next.js whose APIs differ from public docs. **Before writing any frontend route, dynamic-param, or `redirect()` call in tasks 14-15, read** `tutorbot-web/node_modules/next/dist/docs/` for the actual signatures.

**Spec correction (small):** The spec mentions `tests/services/session/` for backend tests, but the existing TutorBot test layout uses `tests/services/tutorbot/`. This plan uses the correct location.

---

## File Structure

### Backend (Python)

| File | Action | Responsibility |
|------|--------|----------------|
| `deeptutor/tutorbot/session/manager.py` | Modify | Add multi-key listing, `ensure_default_session`, `promote_default`, lazy migration |
| `deeptutor/tutorbot/session/ids.py` | **Create** | `new_session_id()` ULID-ish factory; `DEFAULT_SID = "s_default"` constant |
| `deeptutor/tutorbot/agent/tools/lesson.py` | Modify | After `save(session, plan)` in `PlanLessonTool.execute`, call `promote_default` when the session is the default |
| `deeptutor/services/tutorbot/manager.py` | Modify | `send_message` accepts `session_id`; `get_bot_history` accepts `session_id`; new `list_sessions(bot_id)`, `create_session(bot_id)`, `get_tree()`; new `on_session_promoted` callback path |
| `deeptutor/api/routers/tutorbot.py` | Modify | New routes: `GET/POST /sessions`, `GET /sessions/{sid}/history`, `WS /sessions/{sid}/ws`, `GET /tree`. Keep `/history` and `/ws` working against the current default |
| `tests/services/tutorbot/test_session_manager_multi_key.py` | **Create** | Multi-key get/save/list |
| `tests/services/tutorbot/test_session_promotion.py` | **Create** | `promote_default` lifecycle + replan-in-place |
| `tests/services/tutorbot/test_session_migration.py` | **Create** | Legacy JSONL → archived + fresh default |
| `tests/services/tutorbot/test_plan_lesson_promotion.py` | **Create** | `PlanLessonTool` triggers promotion |
| `tests/api/test_tutorbot_sessions_router.py` | **Create** | New REST + WS endpoints |

### Frontend (TypeScript)

| File | Action | Responsibility |
|------|--------|----------------|
| `tutorbot-web/lib/tutorbot-api.ts` | Modify | Add `Session`, `SessionRow`, `BotTreeRow` types; `listSessions`, `createSession`, `getSessionHistory`, `getTree` |
| `tutorbot-web/lib/bot-ws.ts` | Modify | `connectBotWS(botId, sessionId, ...)`; new `session_promoted` event type |
| `tutorbot-web/context/SessionTreeContext.tsx` | **Create** | Tree state, refresh, patch helpers |
| `tutorbot-web/components/ui/AppSidebar.tsx` | Modify | Render the tree (辅导机器人 → bots → sessions) per the spec mockup |
| `tutorbot-web/components/tutorbot/chat/BotChatView.tsx` | Modify | Accept `sessionId` prop; use session-scoped URLs; pipe `session_promoted` to context |
| `tutorbot-web/app/(app)/tutorbot/[botId]/chat/page.tsx` | Modify | Redirect to current default session |
| `tutorbot-web/app/(app)/tutorbot/[botId]/chat/[sessionId]/page.tsx` | **Create** | Real chat page; renders `<BotChatView botId sessionId />` |
| `tutorbot-web/app/(app)/layout.tsx` | Modify | Wrap children in `<SessionTreeProvider>` |
| `tutorbot-web/locales/en/common.json` | Modify | Add five i18n keys |
| `tutorbot-web/locales/zh-CN/common.json` | Modify | Add five i18n keys |

---

## Phase 1 — Backend: SessionManager extensions (TDD)

### Task 1: Session-id factory + default constant

**Files:**
- Create: `deeptutor/tutorbot/session/ids.py`
- Test: `tests/services/tutorbot/test_session_manager_multi_key.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/tutorbot/test_session_manager_multi_key.py
from deeptutor.tutorbot.session.ids import DEFAULT_SID, new_session_id


def test_default_sid_constant():
    assert DEFAULT_SID == "s_default"


def test_new_session_id_unique_and_prefixed():
    ids = {new_session_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(s.startswith("s_") for s in ids)
    assert all(s != DEFAULT_SID for s in ids)
    assert all(8 <= len(s) <= 32 for s in ids)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_manager_multi_key.py -v
```
Expected: FAIL (`ModuleNotFoundError: deeptutor.tutorbot.session.ids`).

- [ ] **Step 3: Implement the module**

```python
# deeptutor/tutorbot/session/ids.py
"""Session id helpers.

DEFAULT_SID is the bootstrap-only well-known id for the very first default
session of a bot. After promotion, defaults get fresh ids from
new_session_id() — ids are immutable for the life of the session.
"""

from __future__ import annotations

import secrets

DEFAULT_SID = "s_default"


def new_session_id() -> str:
    """Return a short URL-safe random id, prefixed `s_`."""
    # 12 hex chars = 48 bits of entropy. Plenty for per-bot uniqueness; short
    # enough to keep filenames and URLs readable.
    return "s_" + secrets.token_hex(6)
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_manager_multi_key.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/tutorbot/session/ids.py tests/services/tutorbot/test_session_manager_multi_key.py
git commit -m "feat(tutorbot/session): add session id factory and DEFAULT_SID constant"
```

---

### Task 2: SessionManager — list sessions for a bot

**Files:**
- Modify: `deeptutor/tutorbot/session/manager.py` (add `list_for_bot`)
- Test: `tests/services/tutorbot/test_session_manager_multi_key.py` (append)

- [ ] **Step 1: Append the failing test**

```python
# Append to tests/services/tutorbot/test_session_manager_multi_key.py

import pytest

from deeptutor.tutorbot.session.manager import SessionManager


def _mk_session(mgr: SessionManager, key: str, status: str = "active", title: str = "", **meta) -> None:
    s = mgr.get_or_create(key)
    s.metadata.update({"status": status, "title": title, **meta})
    s.add_message("user", "hi")
    mgr.save(s)


def test_list_for_bot_returns_only_matching_bot(tmp_path):
    mgr = SessionManager(tmp_path)
    _mk_session(mgr, "bot:b1:s:s_default", status="default")
    _mk_session(mgr, "bot:b1:s:s_aaaa", status="active", title="Alpha")
    _mk_session(mgr, "bot:b2:s:s_bbbb", status="active", title="Beta")

    rows = mgr.list_for_bot("b1")

    keys = [r["key"] for r in rows]
    assert "bot:b1:s:s_default" in keys
    assert "bot:b1:s:s_aaaa" in keys
    assert "bot:b2:s:s_bbbb" not in keys


def test_list_for_bot_orders_default_first_then_updated_at_desc(tmp_path):
    import time

    mgr = SessionManager(tmp_path)
    _mk_session(mgr, "bot:b1:s:s_old", status="active", title="Old")
    time.sleep(0.01)
    _mk_session(mgr, "bot:b1:s:s_default", status="default")
    time.sleep(0.01)
    _mk_session(mgr, "bot:b1:s:s_new", status="active", title="New")

    rows = mgr.list_for_bot("b1")
    statuses = [r["status"] for r in rows]
    titles = [r["title"] for r in rows]

    assert statuses[0] == "default"
    # Among non-default rows, newer first.
    assert titles[1] == "New"
    assert titles[2] == "Old"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_manager_multi_key.py -v
```
Expected: `AttributeError: 'SessionManager' object has no attribute 'list_for_bot'`.

- [ ] **Step 3: Implement `list_for_bot`**

Add to `deeptutor/tutorbot/session/manager.py` (inside `SessionManager`, after `list_sessions`):

```python
    def list_for_bot(self, bot_id: str) -> list[dict[str, Any]]:
        """Return session rows for one bot, default first then updated_at desc.

        Each row: {key, id, title, title_source, status, updated_at, lesson_plan}
        """
        from deeptutor.tutorbot.utils.helpers import safe_filename

        safe_bot = safe_filename(bot_id)
        prefix = f"bot_{safe_bot}_s_"
        rows: list[dict[str, Any]] = []
        for path in self.sessions_dir.glob(f"{prefix}*.jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                if not first_line:
                    continue
                data = json.loads(first_line)
                if data.get("_type") != "metadata":
                    continue
                key = data.get("key") or ""
                meta = data.get("metadata") or {}
                # Derive session_id from filename suffix (after `_s_`).
                sid = path.stem[len(prefix):]
                rows.append({
                    "key": key,
                    "id": f"s_{sid}" if not sid.startswith("s_") else sid,
                    "title": meta.get("title") or "",
                    "title_source": meta.get("title_source"),
                    "status": meta.get("status") or "active",
                    "updated_at": data.get("updated_at"),
                    "lesson_plan": meta.get("lesson_plan"),
                })
            except Exception:
                continue

        def _sort_key(r: dict[str, Any]):
            is_default = 0 if r["status"] == "default" else 1
            return (is_default, -_iso_to_ts(r.get("updated_at")))

        rows.sort(key=_sort_key)
        return rows
```

Also add (top of file, near other helpers — adjust if a helpers module already has one):

```python
def _iso_to_ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return 0.0
```

Note on the id-derivation: the file slug `bot_<safe_bot>_s_<sid>.jsonl` uses `safe_filename` which preserves alphanumerics and `_`. We expect sids like `s_01abcd...`, so stripping the `bot_<bot>_s_` prefix yields `01abcd...` — the snippet re-prepends `s_` if missing. **Verify this against `safe_filename`'s actual behavior** before trusting the round-trip; if the round-trip is lossy, switch to reading the `id` from session metadata (add `id` to the metadata write in Task 3).

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_manager_multi_key.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/tutorbot/session/manager.py tests/services/tutorbot/test_session_manager_multi_key.py
git commit -m "feat(tutorbot/session): list_for_bot — default-first session listing"
```

---

### Task 3: SessionManager — `ensure_default_session(bot_id)`

**Files:**
- Modify: `deeptutor/tutorbot/session/manager.py`
- Test: `tests/services/tutorbot/test_session_manager_multi_key.py` (append)

- [ ] **Step 1: Append failing test**

```python
def test_ensure_default_creates_with_bootstrap_id(tmp_path):
    mgr = SessionManager(tmp_path)
    session = mgr.ensure_default_session("b1")
    assert session.metadata["status"] == "default"
    assert session.key == "bot:b1:s:s_default"

    # Idempotent — second call returns same session.
    again = mgr.ensure_default_session("b1")
    assert again.key == session.key


def test_ensure_default_reuses_existing_default(tmp_path):
    mgr = SessionManager(tmp_path)
    # Simulate a non-bootstrap default created by an earlier promotion.
    s = mgr.get_or_create("bot:b1:s:s_freshdef")
    s.metadata.update({"status": "default", "title": ""})
    mgr.save(s)

    session = mgr.ensure_default_session("b1")
    assert session.key == "bot:b1:s:s_freshdef"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_manager_multi_key.py -v
```
Expected: `AttributeError: ... 'ensure_default_session'`.

- [ ] **Step 3: Implement**

Add to `deeptutor/tutorbot/session/manager.py`:

```python
    def ensure_default_session(self, bot_id: str) -> Session:
        """Return the bot's current default session, creating one if missing.

        Bootstrap-only path uses DEFAULT_SID. Subsequent defaults (created by
        promote_default) have ULID ids; this method just finds whichever
        session currently has status="default".
        """
        from deeptutor.tutorbot.session.ids import DEFAULT_SID

        # First, run lazy migration if a legacy file is present. Implemented
        # in Task 4; here it's a no-op placeholder so this task's tests pass.
        self._maybe_migrate_legacy_bot(bot_id)

        for row in self.list_for_bot(bot_id):
            if row["status"] == "default":
                return self.get_or_create(row["key"])

        key = f"bot:{bot_id}:s:{DEFAULT_SID}"
        session = self.get_or_create(key)
        session.metadata.update({
            "status": "default",
            "title": "",
            "title_source": None,
        })
        self.save(session)
        return session

    def _maybe_migrate_legacy_bot(self, bot_id: str) -> None:
        """Stub for Task 4 — does nothing yet."""
        return
```

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_manager_multi_key.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/tutorbot/session/manager.py tests/services/tutorbot/test_session_manager_multi_key.py
git commit -m "feat(tutorbot/session): ensure_default_session bootstraps current default"
```

---

### Task 4: Lazy migration of legacy per-bot JSONL (G1)

**Files:**
- Modify: `deeptutor/tutorbot/session/manager.py` (replace stub `_maybe_migrate_legacy_bot`)
- Test: `tests/services/tutorbot/test_session_migration.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/services/tutorbot/test_session_migration.py
import json

from deeptutor.tutorbot.session.manager import SessionManager
from deeptutor.tutorbot.utils.helpers import safe_filename


def _write_legacy(tmp_path, bot_id: str, messages: list[dict], lesson_plan: dict | None = None) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    safe_bot = safe_filename(bot_id)
    path = sessions_dir / f"bot_{safe_bot}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        meta = {
            "_type": "metadata",
            "key": f"bot:{bot_id}",
            "created_at": "2026-04-01T00:00:00",
            "updated_at": "2026-04-01T01:00:00",
            "metadata": ({"lesson_plan": lesson_plan} if lesson_plan else {}),
            "last_consolidated": 0,
        }
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def test_migration_creates_archived_session_and_fresh_default(tmp_path):
    bot_id = "math-tutor"
    _write_legacy(tmp_path, bot_id, [
        {"role": "user", "content": "hi", "timestamp": "2026-04-01T00:00:00"},
        {"role": "assistant", "content": "hello", "timestamp": "2026-04-01T00:00:01"},
    ])

    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session(bot_id)

    rows = mgr.list_for_bot(bot_id)
    statuses = sorted(r["status"] for r in rows)
    titles = {r["status"]: r["title"] for r in rows}

    assert statuses == ["archived", "default"]
    assert titles["archived"] == "之前的对话"
    assert default.metadata["status"] == "default"

    # Legacy file was renamed.
    safe_bot = safe_filename(bot_id)
    legacy = tmp_path / "sessions" / f"bot_{safe_bot}.jsonl"
    migrated = tmp_path / "sessions" / f"bot_{safe_bot}.jsonl.migrated"
    assert not legacy.exists()
    assert migrated.exists()


def test_migration_is_idempotent(tmp_path):
    bot_id = "b1"
    _write_legacy(tmp_path, bot_id, [{"role": "user", "content": "hi"}])

    mgr1 = SessionManager(tmp_path)
    mgr1.ensure_default_session(bot_id)
    rows_before = mgr1.list_for_bot(bot_id)

    mgr2 = SessionManager(tmp_path)
    mgr2.ensure_default_session(bot_id)
    rows_after = mgr2.list_for_bot(bot_id)

    assert len(rows_before) == len(rows_after) == 2


def test_migration_refuses_when_both_legacy_and_migrated_exist(tmp_path, caplog):
    bot_id = "b1"
    _write_legacy(tmp_path, bot_id, [{"role": "user", "content": "hi"}])
    safe_bot = safe_filename(bot_id)
    # Create the .migrated sibling first.
    (tmp_path / "sessions" / f"bot_{safe_bot}.jsonl.migrated").write_text("{}\n", encoding="utf-8")

    mgr = SessionManager(tmp_path)
    mgr.ensure_default_session(bot_id)

    # Neither file got deleted, and no archived session was created.
    legacy = tmp_path / "sessions" / f"bot_{safe_bot}.jsonl"
    assert legacy.exists(), "Legacy file should be preserved for operator intervention"
    rows = mgr.list_for_bot(bot_id)
    statuses = sorted(r["status"] for r in rows)
    assert "archived" not in statuses
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_migration.py -v
```
Expected: tests fail (no archived session created — stub `_maybe_migrate_legacy_bot` is a no-op).

- [ ] **Step 3: Implement migration**

Replace the stub in `deeptutor/tutorbot/session/manager.py`:

```python
    def _maybe_migrate_legacy_bot(self, bot_id: str) -> None:
        """G1: collapse legacy bot_<id>.jsonl into one archived session + fresh default."""
        from deeptutor.tutorbot.session.ids import DEFAULT_SID, new_session_id
        from deeptutor.tutorbot.utils.helpers import safe_filename

        safe_bot = safe_filename(bot_id)
        legacy = self.sessions_dir / f"bot_{safe_bot}.jsonl"
        migrated_marker = self.sessions_dir / f"bot_{safe_bot}.jsonl.migrated"

        if not legacy.exists():
            return
        if migrated_marker.exists():
            logger.warning(
                "Legacy session file present alongside .migrated marker for bot {}; "
                "refusing to re-migrate. Resolve manually.",
                bot_id,
            )
            return

        # Read legacy: metadata + messages
        try:
            messages: list[dict[str, Any]] = []
            legacy_lesson: dict | None = None
            with legacy.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        legacy_lesson = (data.get("metadata") or {}).get("lesson_plan")
                    else:
                        messages.append(data)
        except Exception:
            logger.exception("Migration: malformed legacy JSONL for bot {}; leaving in place", bot_id)
            return

        # Archived session: take the legacy messages verbatim.
        archived_sid = new_session_id()
        archived_key = f"bot:{bot_id}:s:{archived_sid}"
        archived = self.get_or_create(archived_key)
        archived.messages = list(messages)
        archived.metadata.update({
            "status": "archived",
            "title": "之前的对话",
            "title_source": "auto",
        })
        if legacy_lesson:
            archived.metadata["lesson_plan"] = legacy_lesson
        self.save(archived)

        # Fresh empty default.
        default_key = f"bot:{bot_id}:s:{DEFAULT_SID}"
        default = self.get_or_create(default_key)
        default.metadata.update({
            "status": "default",
            "title": "",
            "title_source": None,
        })
        self.save(default)

        # Rename legacy file as the migration marker (one-release safety net).
        legacy.rename(migrated_marker)
        logger.info(
            "Migrated legacy session for bot {} ({} messages → archived {})",
            bot_id, len(messages), archived_sid,
        )
```

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_migration.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/tutorbot/session/manager.py tests/services/tutorbot/test_session_migration.py
git commit -m "feat(tutorbot/session): lazy migrate legacy bot_<id>.jsonl → archived + fresh default"
```

---

### Task 5: SessionManager — `promote_default(session, *, title, title_source, completed)`

**Files:**
- Modify: `deeptutor/tutorbot/session/manager.py`
- Test: `tests/services/tutorbot/test_session_promotion.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/services/tutorbot/test_session_promotion.py
from deeptutor.tutorbot.session.manager import SessionManager


def _seed_default_with_msg(tmp_path, bot_id="b1"):
    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session(bot_id)
    default.add_message("user", "what is x?")
    mgr.save(default)
    return mgr, default


def test_promote_default_renames_default_and_allocates_new(tmp_path):
    mgr, default = _seed_default_with_msg(tmp_path)
    promoted, new_default = mgr.promote_default(
        default, title="二元一次方程的解法", title_source="lesson_plan", completed=False,
    )

    assert promoted.key == default.key  # id immutable
    assert promoted.metadata["title"] == "二元一次方程的解法"
    assert promoted.metadata["title_source"] == "lesson_plan"
    assert promoted.metadata["status"] == "active"

    assert new_default.metadata["status"] == "default"
    assert new_default.key != promoted.key

    rows = mgr.list_for_bot("b1")
    keys = {r["key"] for r in rows}
    assert promoted.key in keys
    assert new_default.key in keys
    assert sum(1 for r in rows if r["status"] == "default") == 1


def test_promote_default_with_completed_sets_status(tmp_path):
    mgr, default = _seed_default_with_msg(tmp_path)
    promoted, _ = mgr.promote_default(
        default, title="", title_source="manual", completed=True,
    )
    assert promoted.metadata["status"] == "completed"


def test_promote_default_noop_when_already_promoted(tmp_path):
    mgr, default = _seed_default_with_msg(tmp_path)
    mgr.promote_default(default, title="Lesson A", title_source="lesson_plan", completed=False)
    # Same session reference now has status="active".
    result = mgr.promote_default(default, title="Lesson B", title_source="lesson_plan", completed=False)
    # promote_default must refuse to re-promote — return (session, None) so caller can detect.
    promoted, new_default = result
    assert promoted is default
    assert new_default is None
    # Title was NOT overwritten by this call (replan-in-place handled elsewhere).
    assert promoted.metadata["title"] == "Lesson A"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_promotion.py -v
```
Expected: `AttributeError: ... 'promote_default'`.

- [ ] **Step 3: Implement `promote_default`**

Add to `deeptutor/tutorbot/session/manager.py`:

```python
    def promote_default(
        self,
        session: Session,
        *,
        title: str,
        title_source: str,
        completed: bool,
    ) -> tuple[Session, Session | None]:
        """Promote a default session to active/completed and allocate a new default.

        Returns (promoted, new_default). If the session is already non-default,
        returns (session, None) — caller should use replan-in-place semantics.
        """
        from deeptutor.tutorbot.session.ids import new_session_id

        if session.metadata.get("status") != "default":
            return session, None

        # Extract bot_id from the session key: bot:<id>:s:<sid>
        bot_id = _parse_bot_id_from_key(session.key)
        if bot_id is None:
            raise ValueError(f"Cannot promote — session key lacks bot prefix: {session.key!r}")

        session.metadata["title"] = title
        session.metadata["title_source"] = title_source
        session.metadata["status"] = "completed" if completed else "active"
        self.save(session)

        new_key = f"bot:{bot_id}:s:{new_session_id()}"
        new_default = self.get_or_create(new_key)
        new_default.metadata.update({
            "status": "default",
            "title": "",
            "title_source": None,
        })
        self.save(new_default)
        return session, new_default
```

And add the helper near other module-level helpers:

```python
def _parse_bot_id_from_key(key: str) -> str | None:
    # Key shape: bot:<bot_id>:s:<sid>
    if not key.startswith("bot:"):
        return None
    rest = key[4:]
    sep = rest.rfind(":s:")
    if sep < 0:
        return None
    return rest[:sep]
```

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_session_promotion.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/tutorbot/session/manager.py tests/services/tutorbot/test_session_promotion.py
git commit -m "feat(tutorbot/session): promote_default — atomic default→active + new default"
```

---

## Phase 2 — Backend: wire `plan_lesson` and the promotion event

### Task 6: `PlanLessonTool` triggers `promote_default` for default sessions

**Files:**
- Modify: `deeptutor/tutorbot/agent/tools/lesson.py` (extend `PlanLessonTool.execute`)
- Test: `tests/services/tutorbot/test_plan_lesson_promotion.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/services/tutorbot/test_plan_lesson_promotion.py
import asyncio

from deeptutor.tutorbot.agent.tools.lesson import PlanLessonTool
from deeptutor.tutorbot.session.manager import SessionManager


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_plan_lesson_promotes_default_session(tmp_path):
    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session("b1")
    default.add_message("user", "teach me equations")
    mgr.save(default)

    promotions: list[tuple[str, str | None]] = []

    def on_promoted(promoted_key: str, new_default_key: str | None) -> None:
        promotions.append((promoted_key, new_default_key))

    tool = PlanLessonTool()
    tool.set_session_accessor(
        getter=lambda: default,
        on_update=None,
        session_manager=mgr,
        on_session_promoted=on_promoted,
    )

    result = _run(tool.execute(
        topic="二元一次方程的解法",
        steps=[{"id": "s1", "phase": "define", "goal": "Define linear equation"}],
    ))

    assert "Plan committed" in result
    assert default.metadata["status"] == "active"
    assert default.metadata["title"] == "二元一次方程的解法"
    assert len(promotions) == 1
    promoted_key, new_default_key = promotions[0]
    assert promoted_key == default.key
    assert new_default_key and new_default_key != default.key


def test_plan_lesson_in_active_session_updates_in_place(tmp_path):
    mgr = SessionManager(tmp_path)
    default = mgr.ensure_default_session("b1")
    default.add_message("user", "x?")
    mgr.save(default)
    mgr.promote_default(default, title="Old topic", title_source="lesson_plan", completed=False)

    promotions: list = []
    tool = PlanLessonTool()
    tool.set_session_accessor(
        getter=lambda: default,
        on_update=None,
        session_manager=mgr,
        on_session_promoted=lambda *a: promotions.append(a),
    )

    _run(tool.execute(
        topic="New topic",
        steps=[{"id": "s1", "phase": "define", "goal": "redefine"}],
    ))

    # Title was overwritten (rule 4: replan-in-place), no promotion event.
    assert default.metadata["title"] == "New topic"
    assert promotions == []
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_plan_lesson_promotion.py -v
```
Expected: failure — `set_session_accessor` doesn't accept `session_manager` / `on_session_promoted` yet.

- [ ] **Step 3: Extend the tool**

Modify `deeptutor/tutorbot/agent/tools/lesson.py`. Replace the `_SessionAwareTool.__init__` and `set_session_accessor` and the relevant block of `PlanLessonTool.execute`:

```python
class _SessionAwareTool(Tool):
    """Base for lesson tools — they need the active session and a way to
    notify the WS layer when the plan changes (so the frontend timeline
    can update live)."""

    def __init__(self) -> None:
        self._session_getter: Callable[[], Session | None] = lambda: None
        self._on_update: Callable[[dict], Awaitable[None]] | None = None
        self._session_manager: Any = None
        self._on_session_promoted: Callable[[str, str | None], Any] | None = None

    def set_session_accessor(
        self,
        getter: Callable[[], Session | None],
        on_update: Callable[[dict], Awaitable[None]] | None = None,
        *,
        session_manager: Any = None,
        on_session_promoted: Callable[[str, str | None], Any] | None = None,
    ) -> None:
        """Called by the agent loop at the start of each turn."""
        self._session_getter = getter
        self._on_update = on_update
        self._session_manager = session_manager
        self._on_session_promoted = on_session_promoted
```

Then in `PlanLessonTool.execute`, replace the block that currently ends with `save(session, plan); await self._notify(plan); nudge = ...`:

```python
        # Persist plan on session metadata as before.
        first.status = "in_progress"
        plan.current_step_id = first.id
        save(session, plan)

        # B1 + rule 3/4: promote the default session into a named session,
        # rolling a fresh default. If already active, this is a no-op promotion
        # — we just overwrite the title in place (rule 4).
        if session.metadata.get("status") == "default" and self._session_manager is not None:
            promoted, new_default = self._session_manager.promote_default(
                session, title=plan.topic, title_source="lesson_plan", completed=False,
            )
            if new_default is not None and self._on_session_promoted is not None:
                try:
                    self._on_session_promoted(promoted.key, new_default.key)
                except Exception:
                    _log.exception("on_session_promoted callback raised")
        else:
            # Replan-in-place: keep status, overwrite title to the new topic.
            session.metadata["title"] = plan.topic
            session.metadata["title_source"] = "lesson_plan"
            if self._session_manager is not None:
                self._session_manager.save(session)

        await self._notify(plan)
```

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/services/tutorbot/test_plan_lesson_promotion.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Re-run the full backend smoke set**

```
pytest -q --import-mode=importlib tests/services/tutorbot/
```
Expected: all passing — particularly verify nothing regressed in `test_memory_consolidation_lock.py` or `test_user_isolation.py`.

- [ ] **Step 6: Commit**

```bash
git add deeptutor/tutorbot/agent/tools/lesson.py tests/services/tutorbot/test_plan_lesson_promotion.py
git commit -m "feat(tutorbot/agent): plan_lesson promotes default session into a named one"
```

---

### Task 7: Agent loop passes `session_manager` + promotion callback to lesson tools

**Files:**
- Modify: `deeptutor/tutorbot/agent/loop.py` (where `set_session_accessor` is called)
- Test: covered by Task 8 (integration via WS)

This task wires the new kwargs through. **No new test file**; it's exercised by Task 8's WS test. Tasks 1-6's tests still must pass after this change.

- [ ] **Step 1: Locate the existing `set_session_accessor` call**

```bash
grep -n "set_session_accessor" deeptutor/tutorbot/agent/loop.py
```
Expected: 1+ hits. If absent, search wider: `grep -rn "set_session_accessor" deeptutor/tutorbot/`.

- [ ] **Step 2: Modify the call site**

The agent loop has access to `self.sessions` (a `SessionManager` — see `tutorbot.py` router line 442 `session_mgr = getattr(instance.agent_loop, "sessions", None)`). It does NOT today have a "session promoted" callback channel. Add one:

In the class that owns `set_session_accessor` invocations, add a constructor (or attribute) field:

```python
self._on_session_promoted: Callable[[str, str | None], None] | None = None
```

Add a setter:

```python
def set_session_promoted_callback(self, cb: Callable[[str, str | None], None] | None) -> None:
    self._on_session_promoted = cb
```

Where `set_session_accessor(...)` is currently called per-turn on lesson tools, change to:

```python
tool.set_session_accessor(
    getter=lambda: self._active_session,            # or whatever the existing getter is
    on_update=self._on_lesson_update,               # existing
    session_manager=self.sessions,                  # NEW
    on_session_promoted=self._on_session_promoted,  # NEW
)
```

The exact identifiers (`_active_session`, `_on_lesson_update`) depend on what's already in `loop.py`. **Read the file before editing** and adapt the names; do not break the existing call.

- [ ] **Step 3: Verify backend tests still pass**

```
pytest -q --import-mode=importlib tests/services/tutorbot/
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add deeptutor/tutorbot/agent/loop.py
git commit -m "feat(tutorbot/agent): loop wires session_manager + promotion callback into lesson tools"
```

---

### Task 8: WS handler emits `session_promoted` event

**Files:**
- Modify: `deeptutor/api/routers/tutorbot.py` (extend `bot_chat_ws`)
- Modify: `deeptutor/services/tutorbot/manager.py` (`send_message` accepts an `on_session_promoted` kwarg)
- Test: `tests/api/test_tutorbot_sessions_router.py` (create; full session router test file built up over later tasks)

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_tutorbot_sessions_router.py
"""Tests for the new per-session TutorBot endpoints."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


def _mount(monkeypatch, fake_manager):
    """Stand up a FastAPI app with the router and a fake manager."""
    import deeptutor.api.routers.tutorbot as router_mod

    monkeypatch.setattr(router_mod, "get_tutorbot_manager", lambda: fake_manager)
    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api/v1/tutorbot")
    return TestClient(app)


def test_session_promoted_event_pushed_on_plan_lesson(monkeypatch):
    """When send_message triggers plan_lesson, WS clients receive session_promoted."""
    promoted_payload = {
        "promoted": {"id": "s_default", "title": "Lesson Title",
                     "title_source": "lesson_plan", "lesson_plan_brief": None},
        "new_default": {"id": "s_abc", "title": "", "status": "default"},
    }

    class FakeInstance:
        running = True
        notify_queue = asyncio.Queue()
        agent_loop = SimpleNamespace(sessions=None)

    class FakeMgr:
        def get_bot(self, _bid):
            return FakeInstance()

        def load_bot_config(self, _bid):
            return SimpleNamespace(name="b", channels={}, model=None, llm_selection=None,
                                   description="", persona="")

        async def start_bot(self, *_a, **_kw):
            return FakeInstance()

        async def send_message(self, _bid, _content, *, chat_id, session_id,
                               on_progress=None, on_lesson_update=None,
                               on_session_promoted=None):
            # Simulate the lesson tool firing the promotion callback.
            if on_session_promoted:
                await on_session_promoted(promoted_payload["promoted"],
                                          promoted_payload["new_default"])
            return "reply"

    client = _mount(monkeypatch, FakeMgr())
    with client.websocket_connect("/api/v1/tutorbot/b/sessions/s_default/ws") as ws:
        ws.send_text(json.dumps({"content": "hi"}))
        seen = []
        for _ in range(4):
            msg = ws.receive_json()
            seen.append(msg["type"])
            if msg["type"] == "session_promoted":
                assert msg["promoted"]["title"] == "Lesson Title"
                assert msg["new_default"]["status"] == "default"
                break
        assert "session_promoted" in seen
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: failure — endpoint doesn't exist yet.

- [ ] **Step 3: Add the session-scoped WS endpoint**

Add to `deeptutor/api/routers/tutorbot.py`, after the existing `bot_chat_ws`:

```python
@router.websocket("/{bot_id}/sessions/{sid}/ws")
async def bot_chat_session_ws(ws: WebSocket, bot_id: str, sid: str):
    """Session-scoped WebSocket. Same protocol as /ws, bound to a specific session.

    Pushes a `session_promoted` event when plan_lesson promotes the current
    default — frontends listen and patch their sidebar tree in place.
    """
    disconnected = asyncio.Event()

    async def _safe_send(payload: dict) -> bool:
        try:
            await ws.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError):
            disconnected.set()
            return False

    mgr = get_tutorbot_manager()
    instance = mgr.get_bot(bot_id)
    await ws.accept()

    if not instance or not instance.running:
        config = mgr.load_bot_config(bot_id)
        if config is None:
            await _safe_send({"type": "error", "content": "Bot not found"})
            await ws.close(code=4004, reason="Bot not found")
            return
        lock = await _get_start_lock(bot_id)
        async with lock:
            instance = mgr.get_bot(bot_id)
            if not instance or not instance.running:
                try:
                    instance = await mgr.start_bot(bot_id, config)
                except Exception:
                    logger.exception("Failed to auto-start bot '%s' for session ws", bot_id)
                    await _safe_send({"type": "error", "content": "Failed to start bot"})
                    await ws.close(code=1011, reason="Failed to start bot")
                    return

    logger.info("WebSocket connected for bot '%s' session '%s'", bot_id, sid)

    # Rehydrate lesson plan from THIS session's metadata.
    try:
        session_mgr = getattr(instance.agent_loop, "sessions", None)
        if session_mgr is not None:
            session = session_mgr.get_or_create(f"bot:{bot_id}:s:{sid}")
            plan_dict = (session.metadata or {}).get("lesson_plan")
            if plan_dict:
                await _safe_send({"type": "lesson_plan", "plan": plan_dict})
    except Exception:
        logger.exception("Failed to rehydrate lesson plan for bot '%s' session '%s'", bot_id, sid)

    async def _handle_user_messages():
        while not disconnected.is_set():
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                disconnected.set()
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                if not await _safe_send({"type": "error", "content": "Invalid JSON"}):
                    break
                continue
            content = data.get("content", "").strip()
            if not content:
                continue

            async def on_progress(text: str, *, tool_hint: bool = False, delta: bool = False) -> None:
                payload: dict = {"type": "thinking", "content": text}
                if delta:
                    payload["delta"] = True
                if tool_hint:
                    payload["tool_hint"] = True
                await _safe_send(payload)

            async def on_lesson_update(plan_dict: dict) -> None:
                await _safe_send({"type": "lesson_plan", "plan": plan_dict})

            async def on_session_promoted(promoted: dict, new_default: dict) -> None:
                await _safe_send({
                    "type": "session_promoted",
                    "promoted": promoted,
                    "new_default": new_default,
                })

            try:
                response = await mgr.send_message(
                    bot_id, content,
                    chat_id=data.get("chat_id", "web"),
                    session_id=sid,
                    on_progress=on_progress,
                    on_lesson_update=on_lesson_update,
                    on_session_promoted=on_session_promoted,
                )
                if not await _safe_send({"type": "content", "content": response}):
                    break
                if not await _safe_send({"type": "done"}):
                    break
            except RuntimeError as exc:
                if not await _safe_send({"type": "error", "content": str(exc)}):
                    break
            except WebSocketDisconnect:
                disconnected.set()
                break
            except Exception:
                logger.exception("Error processing session message for bot '%s'", bot_id)
                if not await _safe_send({"type": "error", "content": "Internal error"}):
                    break

    async def _handle_notifications():
        while not disconnected.is_set():
            get_task = asyncio.create_task(instance.notify_queue.get())
            wait_task = asyncio.create_task(disconnected.wait())
            done, pending = await asyncio.wait(
                {get_task, wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if get_task not in done:
                break
            content = get_task.result()
            if not await _safe_send({"type": "proactive", "content": content}):
                break

    user_task = asyncio.create_task(_handle_user_messages())
    notify_task = asyncio.create_task(_handle_notifications())
    try:
        done, pending = await asyncio.wait(
            [user_task, notify_task], return_when=asyncio.FIRST_COMPLETED,
        )
        disconnected.set()
        for t in pending:
            t.cancel()
    except Exception:
        disconnected.set()
        user_task.cancel()
        notify_task.cancel()
    logger.info("WebSocket closed for bot '%s' session '%s'", bot_id, sid)
```

And in `deeptutor/services/tutorbot/manager.py`, modify `send_message`:

```python
    async def send_message(
        self,
        bot_id: str,
        content: str,
        chat_id: str = "web",
        session_id: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_lesson_update: Callable[[dict], Awaitable[None]] | None = None,
        on_session_promoted: Callable[[dict, dict], Awaitable[None]] | None = None,
    ) -> str:
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            raise RuntimeError(f"Bot '{bot_id}' is not running")

        if session_id is None:
            # Backward-compat: default session.
            session_id = (
                instance.agent_loop.sessions.ensure_default_session(bot_id).key.split(":s:")[-1]
            )

        canonical_key = f"bot:{bot_id}:s:{session_id}"

        # Bridge the per-turn promotion callback into the agent loop, which
        # will pass it to lesson tools via set_session_accessor.
        if on_session_promoted is not None:
            def _bridge(promoted_key: str, new_default_key: str | None) -> None:
                # Synchronous → schedule the async ws send.
                async def _emit():
                    sm = instance.agent_loop.sessions
                    promoted = sm.get_or_create(promoted_key)
                    promoted_view = {
                        "id": promoted_key.split(":s:")[-1],
                        "title": promoted.metadata.get("title", ""),
                        "title_source": promoted.metadata.get("title_source"),
                        "lesson_plan_brief": _lesson_brief(promoted.metadata.get("lesson_plan")),
                    }
                    new_default_view = None
                    if new_default_key:
                        nd = sm.get_or_create(new_default_key)
                        new_default_view = {
                            "id": new_default_key.split(":s:")[-1],
                            "title": "",
                            "status": "default",
                        }
                    await on_session_promoted(promoted_view, new_default_view or {})
                asyncio.create_task(_emit())
            instance.agent_loop.set_session_promoted_callback(_bridge)
        else:
            instance.agent_loop.set_session_promoted_callback(None)

        async def _progress(text: str, *, tool_hint: bool = False, delta: bool = False) -> None:
            if on_progress:
                try:
                    await on_progress(text, tool_hint=tool_hint, delta=delta)
                except TypeError:
                    await on_progress(text)

        response = await instance.agent_loop.process_direct(
            content,
            session_key=canonical_key,
            channel="web",
            chat_id=chat_id,
            on_progress=_progress,
            on_lesson_update=on_lesson_update,
        )
        # ... existing channel-forwarding logic unchanged ...
        return response


def _lesson_brief(plan_dict: dict | None) -> dict | None:
    if not plan_dict:
        return None
    steps = plan_dict.get("steps") or []
    return {
        "topic": plan_dict.get("topic", ""),
        "current_step_id": plan_dict.get("current_step_id"),
        "total_steps": len(steps),
        "done_steps": sum(1 for s in steps if s.get("status") in ("done", "skipped")),
    }
```

- [ ] **Step 4: Run to verify the WS test passes**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: `test_session_promoted_event_pushed_on_plan_lesson` passes.

- [ ] **Step 5: Run regression on existing router tests**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_router.py
```
Expected: all green (existing `/ws` and `/history` unchanged).

- [ ] **Step 6: Commit**

```bash
git add deeptutor/api/routers/tutorbot.py deeptutor/services/tutorbot/manager.py tests/api/test_tutorbot_sessions_router.py
git commit -m "feat(api/tutorbot): session-scoped WS + session_promoted live event"
```

---

## Phase 3 — Backend: REST routes

### Task 9: `GET /tutorbot/{bot_id}/sessions`

**Files:**
- Modify: `deeptutor/api/routers/tutorbot.py`
- Modify: `deeptutor/services/tutorbot/manager.py` (new `list_sessions(bot_id)`)
- Test: `tests/api/test_tutorbot_sessions_router.py` (append)

- [ ] **Step 1: Append failing test**

```python
def test_list_sessions_returns_default_first(monkeypatch):
    class FakeMgr:
        def list_sessions(self, _bid):
            return [
                {"id": "s_default", "title": "", "title_source": None,
                 "status": "default", "updated_at": "2026-05-17T10:00:00",
                 "lesson_plan_brief": None},
                {"id": "s_a", "title": "Lesson A", "title_source": "lesson_plan",
                 "status": "active", "updated_at": "2026-05-17T09:00:00",
                 "lesson_plan_brief": {"topic": "Lesson A", "current_step_id": "s1",
                                       "total_steps": 3, "done_steps": 1}},
            ]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/b1/sessions")
    assert res.status_code == 200
    rows = res.json()
    assert rows[0]["status"] == "default"
    assert rows[1]["title"] == "Lesson A"
    assert rows[1]["lesson_plan_brief"]["done_steps"] == 1
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py::test_list_sessions_returns_default_first -v
```
Expected: 404 (route not registered).

- [ ] **Step 3: Add the route + manager method**

In `deeptutor/api/routers/tutorbot.py` (near other `/{bot_id}/...` routes):

```python
@router.get("/{bot_id}/sessions")
async def list_bot_sessions(bot_id: str):
    """List all sessions for a bot. Default session is first, then updated_at desc."""
    return get_tutorbot_manager().list_sessions(bot_id)
```

In `deeptutor/services/tutorbot/manager.py`, add:

```python
    def list_sessions(self, bot_id: str) -> list[dict[str, Any]]:
        """Public wrapper around SessionManager.list_for_bot, decorated with lesson_plan_brief."""
        workspace = self._bot_workspace(bot_id)
        from deeptutor.tutorbot.session.manager import SessionManager as _SM
        sm = _SM(workspace)
        sm.ensure_default_session(bot_id)  # also runs lazy migration

        out: list[dict[str, Any]] = []
        for row in sm.list_for_bot(bot_id):
            out.append({
                "id": row["id"],
                "title": row["title"],
                "title_source": row["title_source"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "lesson_plan_brief": _lesson_brief(row.get("lesson_plan")),
            })
        return out
```

(`_lesson_brief` was added in Task 8.)

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: all tests in this file pass.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/api/routers/tutorbot.py deeptutor/services/tutorbot/manager.py tests/api/test_tutorbot_sessions_router.py
git commit -m "feat(api/tutorbot): GET /sessions — list bot sessions (default first)"
```

---

### Task 10: `POST /tutorbot/{bot_id}/sessions` (M3 rule)

**Files:**
- Modify: `deeptutor/api/routers/tutorbot.py`
- Modify: `deeptutor/services/tutorbot/manager.py` (`create_session(bot_id)`)
- Test: `tests/api/test_tutorbot_sessions_router.py` (append)

- [ ] **Step 1: Append failing tests**

```python
def test_post_sessions_409_when_default_empty(monkeypatch):
    class FakeMgr:
        def create_session(self, _bid):
            # Simulate the M3 rule: default exists and is empty.
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail={"existing_default_id": "s_default"})
    client = _mount(monkeypatch, FakeMgr())
    res = client.post("/api/v1/tutorbot/b1/sessions")
    assert res.status_code == 409
    assert res.json()["detail"]["existing_default_id"] == "s_default"


def test_post_sessions_201_when_default_non_empty(monkeypatch):
    class FakeMgr:
        def create_session(self, _bid):
            return {"id": "s_new", "title": "", "title_source": None,
                    "status": "default", "updated_at": "2026-05-17T10:01:00",
                    "lesson_plan_brief": None}
    client = _mount(monkeypatch, FakeMgr())
    res = client.post("/api/v1/tutorbot/b1/sessions")
    assert res.status_code == 201
    assert res.json()["id"] == "s_new"
    assert res.json()["status"] == "default"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: failure — route absent.

- [ ] **Step 3: Add route + manager method**

In `deeptutor/api/routers/tutorbot.py`:

```python
@router.post("/{bot_id}/sessions", status_code=201)
async def create_bot_session(bot_id: str):
    """Implements the M3 rule: 409 if the current default is empty; else
    promotes the current default with empty title (status=completed) and
    returns the newly-allocated empty default."""
    return get_tutorbot_manager().create_session(bot_id)
```

In `deeptutor/services/tutorbot/manager.py`:

```python
    def create_session(self, bot_id: str) -> dict[str, Any]:
        from fastapi import HTTPException
        workspace = self._bot_workspace(bot_id)
        from deeptutor.tutorbot.session.manager import SessionManager as _SM
        sm = _SM(workspace)
        default = sm.ensure_default_session(bot_id)

        if not default.messages:
            existing_id = default.key.split(":s:")[-1]
            raise HTTPException(
                status_code=409, detail={"existing_default_id": existing_id},
            )

        _, new_default = sm.promote_default(
            default, title="", title_source="manual", completed=True,
        )
        assert new_default is not None  # invariant: was status=default
        return {
            "id": new_default.key.split(":s:")[-1],
            "title": "",
            "title_source": None,
            "status": "default",
            "updated_at": new_default.updated_at.isoformat(),
            "lesson_plan_brief": None,
        }
```

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/api/routers/tutorbot.py deeptutor/services/tutorbot/manager.py tests/api/test_tutorbot_sessions_router.py
git commit -m "feat(api/tutorbot): POST /sessions — M3 manual new chat with 409 guard"
```

---

### Task 11: `GET /tutorbot/{bot_id}/sessions/{sid}/history`

**Files:**
- Modify: `deeptutor/api/routers/tutorbot.py`
- Modify: `deeptutor/services/tutorbot/manager.py` — extend `get_bot_history` with optional `session_id`
- Test: append to `test_tutorbot_sessions_router.py`

- [ ] **Step 1: Append failing test**

```python
def test_get_session_history(monkeypatch):
    class FakeMgr:
        def get_bot_history(self, _bid, *, session_id, limit=100):
            assert session_id == "s_abc"
            return [{"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"}]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/b1/sessions/s_abc/history")
    assert res.status_code == 200
    assert [m["role"] for m in res.json()] == ["user", "assistant"]
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: failure (route absent).

- [ ] **Step 3: Implement**

Route:

```python
@router.get("/{bot_id}/sessions/{sid}/history")
async def get_session_history(bot_id: str, sid: str, limit: int = 100):
    return get_tutorbot_manager().get_bot_history(bot_id, session_id=sid, limit=limit)
```

Modify `get_bot_history` in `deeptutor/services/tutorbot/manager.py`. Change its signature to accept an optional `session_id` (keyword-only) and, when supplied, read only that JSONL:

```python
    def get_bot_history(
        self,
        bot_id: str,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sessions_dir = self._bot_workspace(bot_id) / "sessions"
        if not sessions_dir.exists():
            return []

        if session_id is None:
            # Backward-compat (legacy /history) — resolve to the current default.
            from deeptutor.tutorbot.session.manager import SessionManager as _SM
            session = _SM(self._bot_workspace(bot_id)).ensure_default_session(bot_id)
            session_id = session.key.split(":s:")[-1]

        from deeptutor.tutorbot.utils.helpers import safe_filename
        safe_bot = safe_filename(bot_id)
        path = sessions_dir / f"bot_{safe_bot}_s_{session_id}.jsonl"
        if not path.exists():
            # Fall back to scanning the dir for the file (id may have a prefix).
            matches = list(sessions_dir.glob(f"bot_{safe_bot}_s_{session_id}*.jsonl"))
            if not matches:
                return []
            path = matches[0]

        # Reuse the existing per-file message extraction loop.
        indexed: list[tuple[float, int, dict[str, Any]]] = []
        sequence = 0
        file_mtime = path.stat().st_mtime
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        continue
                    if data.get("role") in ("user", "assistant") and data.get("content"):
                        data["content"] = normalize_message_content(data["content"])
                        data.pop("reasoning_content", None)
                        indexed.append((_history_sort_timestamp(data, file_mtime), sequence, data))
                        sequence += 1
        except Exception:
            return []

        indexed.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in indexed][-limit:]
```

- [ ] **Step 4: Run to verify it passes — plus the regression**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py tests/api/test_tutorbot_router.py -v
```
Expected: all green. The legacy `GET /history` route still passes because it calls `get_bot_history(bot_id, limit=...)` without `session_id`, which now resolves to the default.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/api/routers/tutorbot.py deeptutor/services/tutorbot/manager.py tests/api/test_tutorbot_sessions_router.py
git commit -m "feat(api/tutorbot): GET /sessions/{sid}/history with default-resolving fallback"
```

---

### Task 12: `GET /api/v1/tutorbot/tree`

**Files:**
- Modify: `deeptutor/api/routers/tutorbot.py`
- Modify: `deeptutor/services/tutorbot/manager.py` (`get_tree()`)
- Test: append to `test_tutorbot_sessions_router.py`

- [ ] **Step 1: Append failing test**

```python
def test_tree_returns_all_bots_with_sessions(monkeypatch):
    class FakeMgr:
        def get_tree(self):
            return [
                {"bot_id": "b1", "name": "Math", "running": True, "sessions": [
                    {"id": "s_default", "title": "", "title_source": None,
                     "status": "default", "updated_at": "2026-05-17",
                     "lesson_plan_brief": None},
                ]},
                {"bot_id": "b2", "name": "Chem", "running": False, "sessions": []},
            ]
    client = _mount(monkeypatch, FakeMgr())
    res = client.get("/api/v1/tutorbot/tree")
    assert res.status_code == 200
    tree = res.json()
    assert len(tree) == 2
    assert tree[0]["sessions"][0]["status"] == "default"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py::test_tree_returns_all_bots_with_sessions -v
```
Expected: 404.

- [ ] **Step 3: Implement**

Route (place near the top, before `/{bot_id}` parameterized routes — order matters in FastAPI):

```python
@router.get("/tree")
async def get_tutorbot_tree():
    """Whole sidebar tree: bots + per-bot sessions in one round-trip."""
    return get_tutorbot_manager().get_tree()
```

Manager:

```python
    def get_tree(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for bid in self._discover_bot_ids():
            cfg = self.load_bot_config(bid)
            instance = self._bots.get(bid)
            out.append({
                "bot_id": bid,
                "name": cfg.name if cfg else bid,
                "running": instance.running if instance else False,
                "sessions": self.list_sessions(bid),
            })
        return out
```

- [ ] **Step 4: Run to verify it passes**

```
pytest -q --import-mode=importlib tests/api/test_tutorbot_sessions_router.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add deeptutor/api/routers/tutorbot.py deeptutor/services/tutorbot/manager.py tests/api/test_tutorbot_sessions_router.py
git commit -m "feat(api/tutorbot): GET /tree — one-shot sidebar payload"
```

---

## Phase 4 — Frontend: API client + WebSocket

### Task 13: `tutorbot-api.ts` — session types + API functions

**Files:**
- Modify: `tutorbot-web/lib/tutorbot-api.ts`

- [ ] **Step 1: Append types and API functions**

At the bottom of `tutorbot-web/lib/tutorbot-api.ts`:

```ts
// ── Sessions ─────────────────────────────────────────────────────

export interface LessonPlanBrief {
  topic: string;
  current_step_id: string | null;
  total_steps: number;
  done_steps: number;
}

export type SessionStatus = "default" | "active" | "completed" | "archived";

export interface SessionRow {
  id: string;
  title: string;
  title_source: "lesson_plan" | "manual" | "auto" | null;
  status: SessionStatus;
  updated_at: string;
  lesson_plan_brief: LessonPlanBrief | null;
}

export interface BotTreeRow {
  bot_id: string;
  name: string;
  running: boolean;
  sessions: SessionRow[];
}

export async function listBotSessions(botId: string): Promise<SessionRow[]> {
  return apiFetch(url(`/${botId}/sessions`)).then(r => r.json());
}

/** Returns the new default session, or throws an Error with .code = 409
 *  carrying `{ existing_default_id }` when the current default is empty. */
export async function createBotSession(botId: string): Promise<SessionRow> {
  const res = await apiFetch(url(`/${botId}/sessions`), { method: "POST" });
  if (res.status === 409) {
    const body = await res.json();
    const err = new Error("default-session-empty") as Error & { code: number; data: any };
    err.code = 409;
    err.data = body.detail;
    throw err;
  }
  return res.json();
}

export async function getBotSessionHistory(
  botId: string, sessionId: string, limit = 100,
): Promise<{ role: string; content: string }[]> {
  return apiFetch(url(`/${botId}/sessions/${sessionId}/history?limit=${limit}`)).then(r => r.json());
}

export async function getTutorbotTree(): Promise<BotTreeRow[]> {
  return apiFetch(url(`/tree`)).then(r => r.json());
}
```

- [ ] **Step 2: TypeScript check**

```
cd tutorbot-web && npx tsc --noEmit -p tsconfig.json
```
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add tutorbot-web/lib/tutorbot-api.ts
git commit -m "feat(tutorbot-web/api): session types + list/create/history/tree clients"
```

---

### Task 14: `lib/bot-ws.ts` — `sessionId` parameter + `session_promoted` event

**Files:**
- Modify: `tutorbot-web/lib/bot-ws.ts`

- [ ] **Step 1: Extend the message union and `connectBotWS` signature**

In `tutorbot-web/lib/bot-ws.ts`:

```ts
export interface SessionPromotedEvent {
  type: "session_promoted";
  promoted: {
    id: string;
    title: string;
    title_source: "lesson_plan" | "manual" | "auto" | null;
    lesson_plan_brief: { topic: string; current_step_id: string | null;
                         total_steps: number; done_steps: number } | null;
  };
  new_default: { id: string; title: string; status: "default" };
}

export type BotMessage =
  | { type: "thinking"; content: string; delta?: boolean; tool_hint?: boolean }
  | { type: "content"; content: string }
  | { type: "done" }
  | { type: "error"; content: string }
  | { type: "proactive"; content: string }
  | { type: "lesson_plan"; plan: LessonPlan }
  | SessionPromotedEvent;
```

Replace `connectBotWS` signature and URL:

```ts
export function connectBotWS(
  botId: string,
  sessionId: string,
  onTurnUpdate: (turnId: string, updater: (turn: BotChatTurn) => BotChatTurn) => void,
  signal: AbortSignal,
  callbacks?: {
    onLessonPlan?: (plan: LessonPlan) => void;
    onSessionPromoted?: (ev: SessionPromotedEvent) => void;
  },
): WebSocket {
  const socket = new WebSocket(
    wsUrl(`/api/v1/tutorbot/${botId}/sessions/${sessionId}/ws`),
  );
  // ... rest of the function body unchanged, except:
```

Inside the existing `message` listener, before the `error` branch, add:

```ts
    if (msg.type === "session_promoted") {
      callbacks?.onSessionPromoted?.(msg);
      return;
    }
```

And update the `lesson_plan` branch to read from the new callbacks object:

```ts
    if (msg.type === "lesson_plan") {
      callbacks?.onLessonPlan?.(msg.plan);
      return;
    }
```

- [ ] **Step 2: TypeScript check**

```
cd tutorbot-web && npx tsc --noEmit -p tsconfig.json
```
Expected: callers of the old `connectBotWS` (only `BotChatView.tsx`) now fail. **This is expected** — Task 17 fixes it. Note the failing file path here:

```
components/tutorbot/chat/BotChatView.tsx: expected 4 arguments but got 4 of wrong types
```

- [ ] **Step 3: Commit (with the breakage flagged in the message)**

```bash
git add tutorbot-web/lib/bot-ws.ts
git commit -m "feat(tutorbot-web/ws): connectBotWS takes sessionId; adds session_promoted event

BotChatView updated in the next task."
```

---

## Phase 5 — Frontend: routes + chat view

### Task 15: New `[sessionId]` route segment

**Files:**
- Create: `tutorbot-web/app/(app)/tutorbot/[botId]/chat/[sessionId]/page.tsx`

> **Read `tutorbot-web/node_modules/next/dist/docs/` before writing this** for the current dynamic-segment and `useParams` shape. The snippet below is the publicly-documented shape; if the pre-release version differs, adapt accordingly.

- [ ] **Step 1: Write the file**

```tsx
// tutorbot-web/app/(app)/tutorbot/[botId]/chat/[sessionId]/page.tsx
"use client";

import { useParams } from "next/navigation";
import BotChatView from "@/components/tutorbot/chat/BotChatView";

export default function BotSessionChatPage() {
  const { botId, sessionId } = useParams<{ botId: string; sessionId: string }>();

  return (
    <div className="h-[calc(100vh-0px)]">
      <BotChatView botId={botId} sessionId={sessionId} />
    </div>
  );
}
```

- [ ] **Step 2: Smoke (frontend won't fully build yet — BotChatView prop change comes in Task 17)**

Skip the build check until Task 17 lands; this file is part of the same logical change.

- [ ] **Step 3: Commit**

```bash
git add tutorbot-web/app/\(app\)/tutorbot/\[botId\]/chat/\[sessionId\]/page.tsx
git commit -m "feat(tutorbot-web): new [sessionId] route segment"
```

---

### Task 16: Redirect existing `chat/page.tsx` to the current default session

**Files:**
- Modify: `tutorbot-web/app/(app)/tutorbot/[botId]/chat/page.tsx`

> Again, **consult `tutorbot-web/node_modules/next/dist/docs/`** for the current `useRouter()` / `redirect()` API in this Next.js version.

- [ ] **Step 1: Replace contents**

```tsx
// tutorbot-web/app/(app)/tutorbot/[botId]/chat/page.tsx
"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { listBotSessions } from "@/lib/tutorbot-api";

export default function BotChatRedirectPage() {
  const { botId } = useParams<{ botId: string }>();
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    listBotSessions(botId)
      .then((rows) => {
        if (cancelled) return;
        const def = rows.find((r) => r.status === "default");
        if (def) router.replace(`/tutorbot/${botId}/chat/${def.id}`);
      })
      .catch(() => {/* leave the spinner — user can retry by navigating */});
    return () => { cancelled = true; };
  }, [botId, router]);

  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add tutorbot-web/app/\(app\)/tutorbot/\[botId\]/chat/page.tsx
git commit -m "feat(tutorbot-web): /chat redirects to current default session"
```

---

### Task 17: `BotChatView` accepts `sessionId`, uses session-scoped URLs, pipes promotion event

**Files:**
- Modify: `tutorbot-web/components/tutorbot/chat/BotChatView.tsx`

- [ ] **Step 1: Replace the props + URLs + WS hookup**

Change the component signature:

```tsx
export default function BotChatView({ botId, sessionId }: { botId: string; sessionId: string }) {
```

Update the history-load URL:

```tsx
    apiFetch(apiUrl(`/api/v1/tutorbot/${botId}/sessions/${sessionId}/history`))
```

Update the WS connect (replace the existing `connectBotWS(...)` call):

```tsx
  // Will be wired to SessionTreeContext in Task 20.
  // For now, log the event so we know the channel works.
  useEffect(() => {
    const ac = new AbortController();
    const ws = connectBotWS(botId, sessionId, updateTurn, ac.signal, {
      onLessonPlan: (plan) => setLessonPlan(plan),
      onSessionPromoted: (ev) => {
        console.info("[session-promoted]", ev);
      },
    });
    wsRef.current = ws;
    ws.addEventListener("open", () => setConnected(true));
    ws.addEventListener("close", () => setConnected(false));
    ws.addEventListener("error", () => setConnected(false));
    return () => {
      ac.abort();
      wsRef.current = null;
    };
  }, [botId, sessionId, updateTurn]);
```

- [ ] **Step 2: Type-check the frontend**

```
cd tutorbot-web && npx tsc --noEmit -p tsconfig.json
```
Expected: no errors.

- [ ] **Step 3: Manual smoke** — start backend + frontend, log in, open a bot. The legacy `/chat` URL should bounce to `/chat/<sid>`. Send a "teach me linear equations" message; the bot should call `plan_lesson`, the sidebar will not yet update (that's Task 20) but the console should log `[session-promoted]`.

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/BotChatView.tsx
git commit -m "feat(tutorbot-web/chat): bind BotChatView to a specific session"
```

---

## Phase 6 — Frontend: sidebar tree

### Task 18: `SessionTreeContext`

**Files:**
- Create: `tutorbot-web/context/SessionTreeContext.tsx`
- Modify: `tutorbot-web/app/(app)/layout.tsx` (wrap children)

- [ ] **Step 1: Write the context**

```tsx
// tutorbot-web/context/SessionTreeContext.tsx
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getTutorbotTree, type BotTreeRow, type SessionRow, type SessionPromotedEvent } from "@/lib/tutorbot-api";
// Re-export SessionPromotedEvent shape from bot-ws so callers don't need to import twice:
import type { SessionPromotedEvent as WsPromoted } from "@/lib/bot-ws";

interface SessionTreeState {
  tree: BotTreeRow[];
  expanded: Record<string, boolean>;
  activeBotId: string | null;
  activeSessionId: string | null;
  refresh: () => Promise<void>;
  toggleBot: (botId: string) => void;
  setActive: (botId: string | null, sessionId: string | null) => void;
  patchPromotion: (botId: string, ev: WsPromoted) => void;
}

const EXPAND_KEY = "deeptutor.sidebar.expanded";

function loadExpanded(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem(EXPAND_KEY) || "{}");
  } catch { return {}; }
}

function saveExpanded(map: Record<string, boolean>) {
  if (typeof window === "undefined") return;
  try { localStorage.setItem(EXPAND_KEY, JSON.stringify(map)); } catch { /* ignore quota errors */ }
}

const Context = createContext<SessionTreeState | null>(null);

export function SessionTreeProvider({ children }: { children: React.ReactNode }) {
  const [tree, setTree] = useState<BotTreeRow[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => loadExpanded());
  const [activeBotId, setActiveBotId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const rows = await getTutorbotTree();
      setTree(rows);
    } catch (e) {
      console.warn("Failed to load tutorbot tree", e);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const toggleBot = useCallback((botId: string) => {
    setExpanded((prev) => {
      const next = { ...prev, [botId]: !prev[botId] };
      saveExpanded(next);
      return next;
    });
  }, []);

  const setActive = useCallback((botId: string | null, sessionId: string | null) => {
    setActiveBotId(botId);
    setActiveSessionId(sessionId);
    if (botId) {
      // Auto-expand the active bot.
      setExpanded((prev) => {
        if (prev[botId]) return prev;
        const next = { ...prev, [botId]: true };
        saveExpanded(next);
        return next;
      });
    }
  }, []);

  const patchPromotion = useCallback((botId: string, ev: WsPromoted) => {
    setTree((prev) => prev.map((b) => {
      if (b.bot_id !== botId) return b;
      const sessions: SessionRow[] = b.sessions.map((s) =>
        s.id === ev.promoted.id
          ? { ...s, title: ev.promoted.title, title_source: ev.promoted.title_source,
              status: "active",
              lesson_plan_brief: ev.promoted.lesson_plan_brief }
          : s
      );
      // Insert the new default at the front if not present yet.
      if (!sessions.some((s) => s.id === ev.new_default.id)) {
        sessions.unshift({
          id: ev.new_default.id, title: "", title_source: null,
          status: "default", updated_at: new Date().toISOString(),
          lesson_plan_brief: null,
        });
      }
      return { ...b, sessions };
    }));
  }, []);

  const value = useMemo<SessionTreeState>(() => ({
    tree, expanded, activeBotId, activeSessionId,
    refresh, toggleBot, setActive, patchPromotion,
  }), [tree, expanded, activeBotId, activeSessionId, refresh, toggleBot, setActive, patchPromotion]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSessionTree(): SessionTreeState {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useSessionTree must be used inside SessionTreeProvider");
  return ctx;
}
```

Note: `SessionPromotedEvent` was added in `lib/bot-ws.ts` (Task 14) — re-export it from `lib/tutorbot-api.ts` if needed, or import directly from `lib/bot-ws.ts` as shown.

- [ ] **Step 2: Wrap the app layout**

In `tutorbot-web/app/(app)/layout.tsx`, find the existing provider tree and add `SessionTreeProvider`:

```tsx
import { SessionTreeProvider } from "@/context/SessionTreeContext";

// ... inside the layout's JSX, wrap children:
<SessionTreeProvider>
  {children}
</SessionTreeProvider>
```

- [ ] **Step 3: Type-check**

```
cd tutorbot-web && npx tsc --noEmit -p tsconfig.json
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/context/SessionTreeContext.tsx tutorbot-web/app/\(app\)/layout.tsx
git commit -m "feat(tutorbot-web): SessionTreeContext — sidebar tree state + patch helpers"
```

---

### Task 19: `AppSidebar` renders the tree

**Files:**
- Modify: `tutorbot-web/components/ui/AppSidebar.tsx`
- Modify: `tutorbot-web/locales/en/common.json`
- Modify: `tutorbot-web/locales/zh-CN/common.json`

- [ ] **Step 1: Add i18n keys**

`tutorbot-web/locales/en/common.json` — add these keys (at the top level of the JSON object):

```json
"sidebar.tutorbots": "TutorBot",
"session.new_chat": "New chat",
"session.legacy_title": "Previous chat",
"session.completed_badge": "Done",
"session.archived_badge": "Archived"
```

`tutorbot-web/locales/zh-CN/common.json`:

```json
"sidebar.tutorbots": "辅导机器人",
"session.new_chat": "新会话",
"session.legacy_title": "之前的对话",
"session.completed_badge": "完成",
"session.archived_badge": "归档"
```

Place them in the existing JSON without duplicating keys. If the project uses nested namespaces, place under the appropriate namespace path.

- [ ] **Step 2: Render the tree**

Replace the `<nav>` block of `tutorbot-web/components/ui/AppSidebar.tsx` (lines 45-66) with the tree renderer. **Do not delete** the existing top-level nav items (`Knowledge`, `Souls`); the tree replaces the `TutorBot` row only.

Sketch:

```tsx
import { ChevronDown, ChevronRight, Plus, MessageSquare, Archive } from "lucide-react";
import { useSessionTree } from "@/context/SessionTreeContext";
import { useParams, useRouter } from "next/navigation";
import { createBotSession, type SessionRow } from "@/lib/tutorbot-api";

// inside AppSidebar(), replace the `nav` block:
const { tree, expanded, activeSessionId, toggleBot, refresh } = useSessionTree();
const router = useRouter();
const { sessionId: routeSessionId } = useParams<{ sessionId?: string }>();
const activeSid = routeSessionId ?? activeSessionId;

async function onNewChatClick(botId: string, defaultId: string, defaultIsEmpty: boolean) {
  if (defaultIsEmpty) {
    router.push(`/tutorbot/${botId}/chat/${defaultId}`);
    return;
  }
  try {
    const newDefault = await createBotSession(botId);
    await refresh();
    router.push(`/tutorbot/${botId}/chat/${newDefault.id}`);
  } catch (e: any) {
    if (e?.code === 409) {
      // Race: somebody already promoted. Refresh + navigate to the
      // existing-default the server pointed at.
      const existing = e.data?.existing_default_id;
      await refresh();
      if (existing) router.push(`/tutorbot/${botId}/chat/${existing}`);
    }
  }
}

// ...
<nav className="flex-1 py-3 px-2 space-y-1 overflow-y-auto">
  {!sidebarCollapsed && (
    <div className="px-3 py-1 text-[11px] uppercase tracking-wider text-[var(--muted-foreground)]">
      {t("sidebar.tutorbots")}
    </div>
  )}
  {tree.map((bot) => {
    const isExpanded = expanded[bot.bot_id] ?? false;
    const defaultRow = bot.sessions.find((s) => s.status === "default");
    const defaultIsEmpty = !defaultRow?.updated_at;  // proxy for "no messages"; refined in Task 20
    return (
      <div key={bot.bot_id}>
        <div className="group flex items-center gap-2 px-3 py-2 text-sm rounded-lg hover:bg-[var(--muted)] cursor-pointer">
          <button onClick={() => toggleBot(bot.bot_id)} className="text-[var(--muted-foreground)]">
            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
          <Bot className="h-4 w-4 shrink-0" />
          <span className="flex-1 truncate">{bot.name}</span>
          {bot.running && <span className="h-2 w-2 rounded-full bg-emerald-500" />}
          {defaultRow && (
            <button
              onClick={(e) => { e.stopPropagation(); onNewChatClick(bot.bot_id, defaultRow.id, defaultIsEmpty); }}
              disabled={defaultIsEmpty}
              className="opacity-0 group-hover:opacity-100 disabled:opacity-30 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              title={t("session.new_chat")}
            >
              <Plus className="h-3 w-3" />
            </button>
          )}
        </div>
        {isExpanded && (
          <div className="ml-5 border-l border-[var(--border)] pl-2 space-y-0.5">
            {bot.sessions.map((s) => (
              <SessionRowView key={s.id} bot={bot} session={s} active={s.id === activeSid} />
            ))}
          </div>
        )}
      </div>
    );
  })}
</nav>
```

`SessionRowView` (define inside the same file, below `AppSidebar`):

```tsx
function SessionRowView({ bot, session, active }: { bot: BotTreeRow; session: SessionRow; active: boolean }) {
  const { t } = useTranslation();
  const router = useRouter();
  const title = session.title
    || (session.status === "archived" ? t("session.legacy_title") : t("session.new_chat"));
  const Icon = session.status === "archived" ? Archive : session.status === "default" ? Plus : MessageSquare;
  return (
    <button
      onClick={() => router.push(`/tutorbot/${bot.bot_id}/chat/${session.id}`)}
      className={cn(
        "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-[13px] text-left",
        active
          ? "bg-[var(--primary)]/10 text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      <span className="flex-1 truncate">{title}</span>
      {session.status === "active" && session.lesson_plan_brief && session.lesson_plan_brief.total_steps > 0 && (
        <span className="text-[10px] text-[var(--muted-foreground)]">
          {session.lesson_plan_brief.done_steps}/{session.lesson_plan_brief.total_steps}
        </span>
      )}
      {session.status === "completed" && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--muted)]">
          {t("session.completed_badge")}
        </span>
      )}
      {session.status === "archived" && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--muted)]">
          {t("session.archived_badge")}
        </span>
      )}
    </button>
  );
}
```

Widen the sidebar when not collapsed (line 27):

```tsx
sidebarCollapsed ? "w-[60px]" : "w-[260px]",
```

- [ ] **Step 3: Build smoke**

```
cd tutorbot-web && npm run build
```
Expected: build succeeds. If `useParams` typing balks on the optional `sessionId`, cast it as shown above.

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/components/ui/AppSidebar.tsx tutorbot-web/locales/en/common.json tutorbot-web/locales/zh-CN/common.json
git commit -m "feat(tutorbot-web/sidebar): render bot → sessions tree with M3 + new chat"
```

---

### Task 20: Wire `session_promoted` from `BotChatView` to the sidebar context

**Files:**
- Modify: `tutorbot-web/components/tutorbot/chat/BotChatView.tsx`
- Modify: `tutorbot-web/components/ui/AppSidebar.tsx` (compute `defaultIsEmpty` from message count instead of `updated_at` proxy)

- [ ] **Step 1: Replace the placeholder `console.info`**

In `BotChatView.tsx`, import the context and use it:

```tsx
import { useSessionTree } from "@/context/SessionTreeContext";
// ...
const { patchPromotion, setActive } = useSessionTree();
// On mount, set active session:
useEffect(() => { setActive(botId, sessionId); return () => setActive(null, null); }, [botId, sessionId, setActive]);
```

Then in the WS hookup:

```tsx
const ws = connectBotWS(botId, sessionId, updateTurn, ac.signal, {
  onLessonPlan: (plan) => setLessonPlan(plan),
  onSessionPromoted: (ev) => patchPromotion(botId, ev),
});
```

- [ ] **Step 2: Improve `defaultIsEmpty` detection in `AppSidebar`**

The sidebar can't see the message list; the cheapest signal is the `updated_at` value relative to the session's `created_at`. Simpler and exact: ask the server. Add to `SessionRow`:

In `tutorbot-web/lib/tutorbot-api.ts`, extend `SessionRow`:

```ts
export interface SessionRow {
  id: string;
  title: string;
  title_source: "lesson_plan" | "manual" | "auto" | null;
  status: SessionStatus;
  updated_at: string;
  has_user_messages: boolean;   // NEW
  lesson_plan_brief: LessonPlanBrief | null;
}
```

In `deeptutor/services/tutorbot/manager.py`, in `list_sessions`, add `has_user_messages` to each row. The `list_for_bot` row only carries metadata; we need to peek into the JSONL for at least one user message. Cheapest: while writing the metadata in Task 2, also count user messages and store as `metadata["user_msg_count"]` (kept in sync by `add_message`). For minimum change in this plan, do a lazy file scan here:

```python
        # In list_sessions, after building `out`:
        from deeptutor.tutorbot.utils.helpers import safe_filename
        safe_bot = safe_filename(bot_id)
        for row in out:
            path = workspace / "sessions" / f"bot_{safe_bot}_s_{row['id'].removeprefix('s_')}.jsonl"
            row["has_user_messages"] = _has_user_message(path)
        return out


def _has_user_message(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("_type") == "metadata":
                    continue
                if data.get("role") == "user" and data.get("content"):
                    return True
    except Exception:
        return False
    return False
```

In the API test from Task 9, add `has_user_messages: True` to the fake row to keep the schema check consistent.

Update `AppSidebar.tsx`:

```tsx
const defaultIsEmpty = !!defaultRow && !defaultRow.has_user_messages;
```

- [ ] **Step 3: Build + manual smoke**

```
cd tutorbot-web && npm run build
```

Manual: start backend + frontend; open a bot, send "teach me linear equations". After the response, observe the sidebar — the default row title turns into the lesson topic, and a new "新会话" appears at the top.

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/components/tutorbot/chat/BotChatView.tsx tutorbot-web/components/ui/AppSidebar.tsx tutorbot-web/lib/tutorbot-api.ts deeptutor/services/tutorbot/manager.py tests/api/test_tutorbot_sessions_router.py
git commit -m "feat(tutorbot-web): live sidebar update on session_promoted"
```

---

## Phase 7 — Smoke + sanity

### Task 21: Run full backend smoke suite

- [ ] **Step 1: Run the CI-equivalent set**

```
pytest -q --import-mode=importlib \
  tests/api tests/cli tests/services/test_model_catalog.py \
  tests/services/test_path_service.py tests/services/memory \
  tests/services/session tests/tools tests/services/tutorbot
```
Expected: all green. Any failure here is in scope to fix.

- [ ] **Step 2: Import smoke**

```
python -c "from deeptutor.runtime.orchestrator import ChatOrchestrator"
```
Expected: no error.

- [ ] **Step 3: Pre-commit**

```
pre-commit run --all-files
```
Expected: all hooks pass. Fix any ruff / mypy / detect-secrets issues inline.

- [ ] **Step 4: If anything was fixed, commit**

```bash
git add -A
git commit -m "chore: lint / type fixes from full smoke run"
```

---

### Task 22: Manual end-to-end smoke

Run by the implementing engineer (Windows dev env).

- [ ] **Step 1: Pre-existing bot with legacy JSONL**

Find a bot whose `multi-user/<uid>/tutorbot/<bot_id>/workspace/sessions/` has a `bot_<id>.jsonl` (no `_s_` infix). Start the server, open the bot — verify the sidebar shows:
- one "之前的对话" row tagged 归档
- one empty "新会话" row, selected by default

Verify on disk the legacy file has been renamed to `.migrated`.

- [ ] **Step 2: Fresh bot, lesson flow**

Create a new bot. Open it; sidebar shows just one "新会话". Send "teach me linear equations". When the bot calls `plan_lesson`, the sidebar must:
- rename the current row to the lesson topic (e.g. "二元一次方程的解法")
- insert a fresh "新会话" at the top
- keep the user on the just-promoted session (URL still resolves to the same session id)

- [ ] **Step 3: M3 button**

In the same bot, hover the bot row — the "+" appears next to the bot name. Click it. Because the current default has at least one message (the rolled-fresh default after promotion is empty, so this needs you to have typed in it), the button should be disabled until you send a message. Send "hi", hover, click "+" — a new default appears and you're navigated to it.

- [ ] **Step 4: Resume an old lesson**

Click the just-completed lesson row. Verify history loads, the lesson-plan card reappears, and you can send a follow-up message that lands in that session (URL contains its sid).

- [ ] **Step 5: Trigger replan inside a resumed lesson**

In the resumed lesson, ask "now teach me about quadratics instead". The bot calls `plan_lesson`. Verify the session's title in the sidebar updates to the new topic, and **no new default is created** (rule 4: replan in place).

If any of these fail, file a follow-up task; do not mark the plan complete.

---

## Self-Review (run after the plan, before handoff)

1. **Spec coverage:**
   - B / B1 / R1 / M3 / G1 → Tasks 5, 6, 17, 10, 4 respectively. ✓
   - SessionManager key shape → Tasks 1-5. ✓
   - `promote_default` semantics → Task 5. ✓
   - `session_promoted` WS event → Task 8 (backend) + Task 20 (frontend). ✓
   - REST surface (`/sessions`, `POST /sessions`, `/sessions/{sid}/history`, `WS /sessions/{sid}/ws`, `/tree`) → Tasks 8-12. ✓
   - Backward compat (`GET /history`, `WS /ws`) → Tasks 11, plus existing tests pre-existing. ✓
   - Sidebar tree per Section-3 mockup → Tasks 18, 19, 20. ✓
   - Routes (`/chat`, `/chat/[sessionId]`) → Tasks 15, 16. ✓
   - i18n keys → Task 19. ✓
   - Testing matrix → Tasks 1-12 (backend) + Task 22 (manual). Note: spec mentioned a Playwright suite for `tutorbot-web/` but the repo has no such suite today; covered by manual smoke (Task 22).
   - Out-of-scope items (PATCH/DELETE wiring, sessions search, SQLite index) → omitted on purpose. ✓
2. **Placeholder scan:** No "TBD", "implement later", or "similar to Task N" — every step shows actual code or commands. ✓
3. **Type / name consistency:**
   - `SessionRow` shape consistent across `tutorbot-api.ts`, `AppSidebar.tsx`, `SessionTreeContext.tsx`, and the test fixtures. ✓
   - `promote_default(session, *, title, title_source, completed)` signature consistent across Tasks 5, 6, 10. ✓
   - `on_session_promoted(promoted_dict, new_default_dict)` callback shape consistent across Tasks 6-8 and Task 14 (frontend). ✓
   - `connectBotWS(botId, sessionId, updateTurn, signal, callbacks)` signature matches Tasks 14, 17. ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-sidebar-session-tree.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
