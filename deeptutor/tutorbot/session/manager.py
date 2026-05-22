"""Session management for conversation history."""

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any

from loguru import logger

from deeptutor.tutorbot.config.paths import get_legacy_sessions_dir
from deeptutor.tutorbot.utils.helpers import ensure_dir, safe_filename


def _iso_to_ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return 0.0


def _parse_bot_id_from_key(key: str) -> str | None:
    """Key shape: bot:<bot_id>:s:<sid>."""
    if not key.startswith("bot:"):
        return None
    rest = key[4:]
    sep = rest.rfind(":s:")
    if sep < 0:
        return None
    return rest[:sep]


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {"role": role, "content": content, "timestamp": datetime.now().isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a user turn."""
        unconsolidated = self.messages[self.last_consolidated :]
        sliced = unconsolidated[-max_messages:]

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            content = m.get("content", "")
            # Shallow-copy the content list so downstream mutations (in
            # particular the LLM provider's strip-image-on-retry path,
            # which does `content[idx] = {...}`) don't bleed back into
            # self.messages and end up persisted to disk on the next save.
            if isinstance(content, list):
                content = list(content)
            entry: dict[str, Any] = {"role": m["role"], "content": content}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.tutorbot/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = (
                            datetime.fromisoformat(data["created_at"])
                            if data.get("created_at")
                            else None
                        )
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    # ── Multi-session-per-bot helpers ─────────────────────────────

    def list_for_bot(self, bot_id: str) -> list[dict[str, Any]]:
        """Return session rows for one bot, default first then updated_at desc.

        Each row: {key, id, title, title_source, status, updated_at, lesson_plan}
        """
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
                sid_tail = path.stem[len(prefix):]
                sid = sid_tail if sid_tail.startswith("s_") else f"s_{sid_tail}"
                rows.append({
                    "key": key,
                    "id": sid,
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

    def ensure_default_session(self, bot_id: str) -> Session:
        """Return the bot's current default session, creating one if missing.

        Bootstrap-only path uses DEFAULT_SID. Subsequent defaults (created by
        promote_default) have ULID ids; this method just finds whichever
        session currently has status="default".
        """
        from deeptutor.tutorbot.session.ids import DEFAULT_SID

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

    def fork_to_new_lesson(
        self,
        session: Session,
        *,
        title: str,
        title_source: str,
    ) -> tuple[Session, Session, Session]:
        """Complete the current session and branch to a fresh lesson session + new default.

        Used by plan_lesson when called with a different topic on an already-named
        session. Marks the current session completed (title preserved), creates a new
        active session for the new lesson topic, and allocates a fresh default.

        Returns (completed_old, new_lesson, new_default).
        """
        from deeptutor.tutorbot.session.ids import new_session_id

        bot_id = _parse_bot_id_from_key(session.key)
        if bot_id is None:
            raise ValueError(
                f"Cannot fork — session key lacks bot prefix: {session.key!r}"
            )

        session.metadata["status"] = "completed"
        self.save(session)

        lesson_key = f"bot:{bot_id}:s:{new_session_id()}"
        lesson_session = self.get_or_create(lesson_key)
        lesson_session.metadata.update(
            {"status": "active", "title": title, "title_source": title_source}
        )
        self.save(lesson_session)

        default_key = f"bot:{bot_id}:s:{new_session_id()}"
        new_default = self.get_or_create(default_key)
        new_default.metadata.update(
            {"status": "default", "title": "", "title_source": None}
        )
        self.save(new_default)

        return session, lesson_session, new_default

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

    def _maybe_migrate_legacy_bot(self, bot_id: str) -> None:
        """G1: collapse legacy bot_<id>.jsonl into one archived session + fresh default."""
        from deeptutor.tutorbot.session.ids import DEFAULT_SID, new_session_id

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

        default_key = f"bot:{bot_id}:s:{DEFAULT_SID}"
        default = self.get_or_create(default_key)
        default.metadata.update({
            "status": "default",
            "title": "",
            "title_source": None,
        })
        self.save(default)

        legacy.rename(migrated_marker)
        logger.info(
            "Migrated legacy session for bot {} ({} messages → archived {})",
            bot_id, len(messages), archived_sid,
        )

    # ── Legacy listing (cross-bot) ────────────────────────────────

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append(
                                {
                                    "key": key,
                                    "created_at": data.get("created_at"),
                                    "updated_at": data.get("updated_at"),
                                    "path": str(path),
                                }
                            )
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
