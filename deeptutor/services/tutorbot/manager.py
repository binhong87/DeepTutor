"""
TutorBot Manager — spawn / stop / manage in-process TutorBot instances.

Each TutorBot instance runs as a set of asyncio tasks within the DeepTutor
server process.  Every bot gets its own isolated workspace under
``multi-user/<uid>/tutorbot/{bot_id}/`` containing workspace, cron, logs, and media.
Memory is per-user at ``multi-user/<uid>/memory/`` (never shared across users).
One TutorBotManager is created per user and cached in ``_managers``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import mimetypes as _mimetypes
from pathlib import Path
import re
import shutil
import sys
from typing import Any

import yaml

from deeptutor.multi_user.models import UserScope

logger = logging.getLogger(__name__)

_PACKAGE_TUTORBOT = Path(__file__).resolve().parent.parent.parent / "tutorbot"
_BUILTIN_SKILLS_DIR = _PACKAGE_TUTORBOT / "skills"
_BUILTIN_TEMPLATES_DIR = _PACKAGE_TUTORBOT / "templates"

_RESERVED_NAMES = {"workspace", "media", "cron", "logs", "sessions", "_souls"}

# Substrings (case-insensitive) on channel field names that flag a value as a
# secret which must be masked before being serialised in non-edit responses.
# Matches existing channel configs: telegram.token, slack.bot_token /
# slack.app_token, discord.token, matrix.access_token, whatsapp.bridge_token,
# mochat.claw_token, feishu.app_secret / encrypt_key / verification_token,
# wecom.secret, qq.secret, dingtalk.client_secret, email.imap_password /
# smtp_password, etc.
_SECRET_FIELD_HINTS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "encrypt_key",
)
_SECRET_MASK = "***"


def _is_secret_field(name: str) -> bool:
    n = name.lower()
    return any(hint in n for hint in _SECRET_FIELD_HINTS)


def mask_channel_secrets(channels: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy ``channels`` and replace any secret-looking string field with ``***``.

    Lists/tuples are walked element-wise; non-string secret values are passed
    through unchanged so we don't accidentally hide non-credential booleans
    (e.g. a ``token_required`` flag, hypothetical).
    """

    def _walk(value: Any, key_hint: str | None = None) -> Any:
        if isinstance(value, dict):
            return {k: _walk(v, key_hint=k) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v, key_hint=key_hint) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v, key_hint=key_hint) for v in value)
        if key_hint is not None and _is_secret_field(key_hint) and isinstance(value, str) and value:
            return _SECRET_MASK
        return value

    walked = _walk(channels)
    if not isinstance(walked, dict):  # defensive — should not happen
        return {}
    return walked


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


def normalize_message_content(content: Any) -> str:
    """Return a display-safe string for text or multimodal message content."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part for part in (normalize_message_content(item) for item in content) if part
        )
    if isinstance(content, dict):
        for key in ("text", "content", "message", "alt"):
            value = content.get(key)
            if isinstance(value, str) and value:
                return value
        if content.get("type") in {"image", "image_url"}:
            return "[image]"
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content)
    return str(content)


_ATTACHMENT_URL_PREFIX = "/api/attachments/"

# Legacy turns may carry a text part like "[image: /api/attachments/...]"
# instead of an image_url block — this happens when a prior LLM call hit
# the strip-image-on-retry path and the mutated content was then persisted.
# Recognise the placeholder so the bubble still renders the attachment.
_PLACEHOLDER_URL_RE = re.compile(
    r"\[image:\s*(/api/attachments/[^\]\s]+)\]", re.IGNORECASE
)


def _extract_attachments_and_clean_content(content: Any) -> tuple[str, list[dict] | None]:
    """Split a multimodal content list into (display_text, attachments).

    For each image_url part whose URL starts with /api/attachments/, emit
    a flat attachment dict and skip it from the text rendering. Text parts
    that match the legacy ``[image: /api/attachments/...]`` placeholder
    (left behind by an earlier strip-image-retry pollution) are also
    recovered as attachments. All other parts go through
    ``normalize_message_content`` as before.

    Returns ``(text, None)`` when there are no attachment parts —
    behavior is unchanged for text-only entries.
    """
    if not isinstance(content, list):
        return normalize_message_content(content), None

    attachments: list[dict] = []
    text_parts: list[Any] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if isinstance(url, str) and url.startswith(_ATTACHMENT_URL_PREFIX):
                filename = url.rsplit("/", 1)[-1]
                attachments.append({
                    "type": "image",
                    "url": url,
                    "mime_type": _mimetypes.guess_type(filename)[0] or "",
                    "filename": filename,
                })
                continue  # don't include in display text
        if isinstance(part, dict) and part.get("type") == "text":
            text_value = part.get("text")
            if isinstance(text_value, str):
                match = _PLACEHOLDER_URL_RE.search(text_value)
                if match:
                    url = match.group(1)
                    filename = url.rsplit("/", 1)[-1]
                    attachments.append({
                        "type": "image",
                        "url": url,
                        "mime_type": _mimetypes.guess_type(filename)[0] or "",
                        "filename": filename,
                    })
                    leftover = (text_value[: match.start()] + text_value[match.end():]).strip()
                    if leftover:
                        text_parts.append({"type": "text", "text": leftover})
                    continue
        text_parts.append(part)

    text = normalize_message_content(text_parts) if text_parts else ""
    return text, (attachments or None)


def _history_sort_timestamp(message: dict[str, Any], fallback: float) -> float:
    """Return a numeric timestamp for stable cross-session history ordering."""
    raw = message.get("timestamp")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


@dataclass
class BotConfig:
    """Configuration for a single TutorBot instance."""

    name: str
    description: str = ""
    persona: str = ""
    channels: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    llm_selection: dict[str, str] | None = None


@dataclass
class TutorBotInstance:
    """A running TutorBot and its metadata."""

    bot_id: str
    config: BotConfig
    owner_id: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    tasks: list[asyncio.Task] = field(default_factory=list, repr=False)
    agent_loop: Any = None
    bus: Any = None
    channel_manager: Any = None
    heartbeat: Any = None
    notify_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    channel_bindings: dict[str, str] = field(default_factory=dict)
    # Serialise concurrent reload_channels invocations on the same bot.
    reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Last error from reload_channels (clears on success); surfaced via API
    # so the UI can warn that on-disk config and live listeners diverged.
    last_reload_error: str | None = None

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self.tasks)

    def to_dict(
        self,
        *,
        include_secrets: bool = False,
        mask_secrets: bool = False,
    ) -> dict[str, Any]:
        """Serialise instance to a JSON-friendly dict.

        Channel field shape:
        - default (``include_secrets=False, mask_secrets=False``): list of channel
          names — safe for list / index endpoints.
        - ``mask_secrets=True``: full nested dict, but secret-looking strings
          replaced with ``***`` — safe for read-only detail views.
        - ``include_secrets=True``: full nested dict including raw secrets —
          ONLY use for the admin edit form (and only on the explicitly-opt-in
          single-bot GET).
        """
        if include_secrets:
            channels: Any = self.config.channels
        elif mask_secrets:
            channels = mask_channel_secrets(self.config.channels)
        else:
            channels = list(self.config.channels.keys())

        return {
            "bot_id": self.bot_id,
            "name": self.config.name,
            "description": self.config.description,
            "persona": self.config.persona,
            "channels": channels,
            "model": self.config.model,
            "llm_selection": self.config.llm_selection,
            "running": self.running,
            "started_at": self.started_at.isoformat(),
            "last_reload_error": self.last_reload_error,
        }


class TutorBotManager:
    """Manage TutorBot instances for a single user (one manager per user)."""

    def __init__(self, *, scope: UserScope) -> None:
        from deeptutor.multi_user.paths import get_path_service_for_scope

        self._scope = scope
        self._path_service = get_path_service_for_scope(scope)
        self._bots: dict[str, TutorBotInstance] = {}
        from deeptutor.tutorbot.worker.manager import BotProcessManager
        self._bot_process_manager = BotProcessManager()

    # ── Path helpers ──────────────────────────────────────────────

    @property
    def _tutorbot_dir(self) -> Path:
        return self._scope.root / "tutorbot"

    @property
    def _memory_dir(self) -> Path:
        return self._scope.root / "memory"

    @property
    def _user_souls_file(self) -> Path:
        return self._tutorbot_dir / "_souls.yaml"

    @staticmethod
    def _builtin_souls_file() -> Path:
        return (
            Path(__file__).resolve().parent.parent.parent
            / "tutorbot" / "souls" / "_builtin.yaml"
        )

    def _bot_dir(self, bot_id: str) -> Path:
        return self._tutorbot_dir / bot_id

    def _bot_workspace(self, bot_id: str) -> Path:
        return self._bot_dir(bot_id) / "workspace"

    # ── Per-bot directory setup ───────────────────────────────────

    def _ensure_bot_dirs(self, bot_id: str) -> None:
        """Create the per-bot directory tree and seed skills/templates."""
        self._maybe_migrate_legacy(bot_id)

        for sub in ("workspace/skills", "workspace/memory", "cron", "logs", "media"):
            (self._bot_dir(bot_id) / sub).mkdir(parents=True, exist_ok=True)

        self._seed_skills(bot_id)
        self._seed_templates(bot_id)

    def _seed_skills(self, bot_id: str) -> None:
        """Copy built-in skill templates into the bot's workspace if absent."""
        if not _BUILTIN_SKILLS_DIR.exists():
            logger.warning("Builtin skills dir not found: %s", _BUILTIN_SKILLS_DIR)
            return
        dst = self._bot_workspace(bot_id) / "skills"
        dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        for skill_dir in _BUILTIN_SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            target = dst / skill_dir.name
            if not target.exists():
                try:
                    shutil.copytree(skill_dir, target)
                    copied += 1
                except Exception:
                    logger.exception(
                        "Failed to copy skill '%s' for bot '%s'", skill_dir.name, bot_id
                    )
        if copied:
            logger.info(
                "Seeded %d skills for bot '%s' from %s", copied, bot_id, _BUILTIN_SKILLS_DIR
            )

    def _seed_templates(self, bot_id: str) -> None:
        """Copy per-bot template files into the bot's workspace if absent."""
        if not _BUILTIN_TEMPLATES_DIR.exists():
            return
        ws = self._bot_workspace(bot_id)
        for tpl in ("SOUL.md", "TOOLS.md", "USER.md", "HEARTBEAT.md", "AGENTS.md"):
            src = _BUILTIN_TEMPLATES_DIR / tpl
            dst = ws / tpl
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    # ── Legacy data migration ─────────────────────────────────────

    def _maybe_migrate_legacy(self, bot_id: str) -> None:
        """Migrate from the old bots/ sub-directory layout.

        Old layout:
          data/tutorbot/bots/{bot_id}/config.yaml
          data/tutorbot/bots/{bot_id}/workspace/
          data/tutorbot/bots/{bot_id}/memory/

        New layout:
          data/tutorbot/{bot_id}/config.yaml
          data/tutorbot/{bot_id}/workspace/
          data/memory/   (shared)
        """
        new_config = self._bot_dir(bot_id) / "config.yaml"
        if new_config.exists():
            return

        legacy_bots = self._tutorbot_dir / "bots"

        # Migrate from bots/{id}/ to {id}/
        legacy_bot_dir = legacy_bots / bot_id
        if legacy_bot_dir.is_dir() and (legacy_bot_dir / "config.yaml").exists():
            target = self._bot_dir(bot_id)
            target.mkdir(parents=True, exist_ok=True)
            for item in legacy_bot_dir.iterdir():
                if item.name == "memory":
                    continue
                dest = target / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            logger.info("Migrated bot '%s' from bots/ sub-directory", bot_id)

        # Migrate legacy bots/{id}.yaml
        legacy_yaml = legacy_bots / f"{bot_id}.yaml"
        if legacy_yaml.is_file() and not new_config.exists():
            self._bot_dir(bot_id).mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_yaml), str(new_config))
            logger.info("Migrated bot config %s.yaml", bot_id)

    # ── Config persistence ────────────────────────────────────────

    # Field names from BotConfig that are persisted via merge.
    _MERGEABLE_FIELDS = (
        "name",
        "description",
        "persona",
        "channels",
        "model",
        "llm_selection",
    )

    def load_bot_config(self, bot_id: str) -> BotConfig | None:
        """Read the on-disk ``config.yaml`` for a bot, or ``None`` if missing."""
        path = self._bot_dir(bot_id) / "config.yaml"
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return BotConfig(
                name=data.get("name", bot_id),
                description=data.get("description", ""),
                persona=data.get("persona", ""),
                channels=data.get("channels", {}),
                model=data.get("model"),
                llm_selection=data.get("llm_selection"),
            )
        except Exception:
            logger.exception("Failed to load bot config %s", bot_id)
            return None

    def save_bot_config(self, bot_id: str, config: BotConfig, *, auto_start: bool = True) -> None:
        """Persist ``config`` to ``config.yaml`` atomically (write-temp + replace).

        Atomic write ensures we never leave a half-written/corrupt yaml on disk
        if the process is killed mid-write.
        """
        bot_dir = self._bot_dir(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        path = bot_dir / "config.yaml"
        data: dict[str, Any] = {
            "name": config.name,
            "description": config.description,
            "persona": config.persona,
            "channels": config.channels,
            "auto_start": auto_start,
        }
        if config.model:
            data["model"] = config.model
        if config.llm_selection:
            data["llm_selection"] = config.llm_selection

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        tmp_path.replace(path)

    def _load_auto_start(self, bot_id: str, *, default: bool = False) -> bool:
        """Read the persisted auto-start intent without loading the full bot config."""
        path = self._bot_dir(bot_id) / "config.yaml"
        if not path.exists():
            return default
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return bool(data.get("auto_start", default))
        except Exception:
            logger.exception("Failed to load auto_start flag for bot '%s'", bot_id)
            return default

    def merge_bot_config(self, bot_id: str, overrides: dict[str, Any]) -> BotConfig:
        """Build a ``BotConfig`` by overlaying ``overrides`` onto the on-disk config.

        Keys in ``overrides`` whose value is ``None`` are treated as "not provided"
        and fall through to the existing on-disk value (or to the dataclass default
        for a brand-new bot). Empty strings / empty dicts are intentional clears
        and DO override — callers must use ``None`` to mean "leave as-is".

        Unknown keys are silently ignored.
        """
        existing = self.load_bot_config(bot_id)
        base = existing or BotConfig(name=bot_id)
        for key in self._MERGEABLE_FIELDS:
            if key in overrides and overrides[key] is not None:
                setattr(base, key, overrides[key])
        return base

    # ── Bot lifecycle ─────────────────────────────────────────────

    async def start_bot(self, bot_id: str, config: BotConfig | None = None) -> TutorBotInstance:
        """Start a TutorBot instance with its own isolated workspace."""
        if bot_id in self._bots and self._bots[bot_id].running:
            return self._bots[bot_id]

        self._ensure_bot_dirs(bot_id)

        if config is None:
            config = self.load_bot_config(bot_id)
        if config is None:
            config = BotConfig(name=bot_id)
            self.save_bot_config(bot_id, config)

        from deeptutor.services.tutorbot.model_runtime import (
            resolve_tutorbot_llm_config,
        )
        from deeptutor.tutorbot.agent.loop import AgentLoop
        from deeptutor.tutorbot.bus.sqlite_queue import SqliteMessageBus
        from deeptutor.tutorbot.config.schema import ExecToolConfig
        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
        from deeptutor.tutorbot.session.manager import SessionManager

        import os

        redis_url = os.getenv("REDIS_URL")
        llm_config = resolve_tutorbot_llm_config(config)
        provider = create_deeptutor_provider(llm_config)
        workspace = self._bot_workspace(bot_id)

        if redis_url:
            from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus
            bus = RedisMessageBus(bot_id=bot_id, redis_url=redis_url)
            await bus.replay_pending()
        else:
            bus = SqliteMessageBus(db_path=workspace / "queue.db")
            await bus.replay_pending()

        session_adapter = SessionManager(workspace)

        if config.persona:
            soul_path = workspace / "SOUL.md"
            soul_path.write_text(config.persona, encoding="utf-8")

        venv_bin = str(Path(sys.executable).parent)
        exec_config = ExecToolConfig(timeout=300, path_append=venv_bin)

        canonical_key = f"bot:{bot_id}"

        if redis_url:
            # AgentLoop runs in a worker process — do not create it in main process
            agent_loop = None
        else:
            agent_loop = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=workspace,
                model=llm_config.model,
                context_window_tokens=llm_config.context_window or 65_536,
                exec_config=exec_config,
                session_manager=session_adapter,
                user_memory_dir=self._memory_dir,
                user_id=self._scope.user_id,
                restrict_to_workspace=False,
                default_session_key=canonical_key,
            )

        # -- Channel setup ---------------------------------------------------
        try:
            channel_manager = self._build_channel_manager(config, bus, bot_id=bot_id)
        except Exception:
            logger.exception("Failed to initialise channels for bot '%s'", bot_id)
            channel_manager = None

        instance = TutorBotInstance(
            bot_id=bot_id,
            config=config,
            agent_loop=agent_loop,
            channel_manager=channel_manager,
        )
        instance.bus = bus

        # -- Core tasks -------------------------------------------------------
        if redis_url:
            # Worker process handles AgentLoop; main process only routes outbound
            import dataclasses as _dc
            config_dict = _dc.asdict(config) if _dc.is_dataclass(config) else dict(vars(config))
            await self._bot_process_manager.start(
                bot_id, workspace, redis_url, config_dict
            )
        else:
            loop_task = asyncio.create_task(
                agent_loop.run(),
                name=f"tutorbot:{bot_id}:loop",
            )
            instance.tasks.append(loop_task)

        router_task = asyncio.create_task(
            self._outbound_router(bot_id, bus, instance),
            name=f"tutorbot:{bot_id}:router",
        )
        instance.tasks.append(router_task)

        # -- Start channel listeners (without ChannelManager's own dispatcher)
        if channel_manager:
            for ch_name, ch in channel_manager.channels.items():
                ch_task = asyncio.create_task(
                    ch.start(),
                    name=f"tutorbot:{bot_id}:ch:{ch_name}",
                )
                instance.tasks.append(ch_task)

        # -- Heartbeat --------------------------------------------------------
        if not redis_url:
            from deeptutor.tutorbot.heartbeat import HeartbeatService

            async def _hb_execute(tasks_summary: str) -> str:
                return await agent_loop.process_direct(
                    tasks_summary,
                    session_key=canonical_key,
                    channel="web",
                    chat_id="web",
                )

            async def _hb_notify(response: str) -> None:
                await instance.notify_queue.put(response)

            heartbeat = HeartbeatService(
                workspace=workspace,
                provider=provider,
                model=agent_loop.model,
                on_execute=_hb_execute,
                on_notify=_hb_notify,
                interval_s=30 * 60,
            )
            instance.heartbeat = heartbeat
            await heartbeat.start()

        instance.owner_id = self._scope.user_id
        self._bots[bot_id] = instance
        self.save_bot_config(bot_id, config)
        logger.info("TutorBot '%s' started (workspace=%s)", bot_id, workspace)
        return instance

    async def reload_llm(self, bot_id: str) -> None:
        """Apply the bot's current LLM config to an already-running instance."""
        instance = self._bots.get(bot_id)
        if not instance or not instance.running or not instance.agent_loop:
            return

        from deeptutor.services.tutorbot.model_runtime import (
            resolve_tutorbot_llm_config,
        )
        from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider

        llm_config = resolve_tutorbot_llm_config(instance.config)
        provider = create_deeptutor_provider(llm_config)
        context_window_tokens = (
            llm_config.context_window or instance.agent_loop.context_window_tokens
        )
        instance.agent_loop.update_llm(
            provider=provider,
            model=llm_config.model,
            context_window_tokens=context_window_tokens,
        )
        if instance.heartbeat:
            instance.heartbeat.provider = provider
            instance.heartbeat.model = instance.agent_loop.model
        logger.info("Reloaded LLM for TutorBot '%s' (model=%s)", bot_id, llm_config.model)

    async def _outbound_router(self, bot_id: str, bus: Any, instance: TutorBotInstance) -> None:
        """Route outbound messages to channels, web notify_queue, and EventBus.

        This is the sole consumer of the outbound queue, replacing both the
        old ``_bridge_events`` and ``ChannelManager._dispatch_outbound`` to
        avoid queue contention.
        """
        try:
            from deeptutor.events.event_bus import Event, EventType, get_event_bus
            from deeptutor.tutorbot.bus.events import OutboundMessage as _OMsg

            event_bus = get_event_bus()
            while True:
                msg: _OMsg = await bus.consume_outbound()
                is_progress = bool(msg.metadata and msg.metadata.get("_progress"))

                # 1. Route to originating channel (if it exists)
                if instance.channel_manager:
                    channel = instance.channel_manager.get_channel(msg.channel)
                    if channel:
                        try:
                            await channel.send(msg)
                        except Exception:
                            logger.exception(
                                "Failed to send to channel %s for bot %s", msg.channel, bot_id
                            )
                        if not is_progress and msg.chat_id:
                            instance.channel_bindings[msg.channel] = msg.chat_id

                # 2. Notify web clients (non-progress only)
                if not is_progress:
                    await instance.notify_queue.put(msg.content or "")

                # 3. Publish to EventBus
                if not is_progress:
                    await event_bus.publish(
                        Event(
                            type=EventType.CAPABILITY_COMPLETE,
                            task_id=f"tutorbot:{bot_id}:{msg.channel}:{msg.chat_id}",
                            user_input="",
                            agent_output=msg.content or "",
                            metadata={
                                "source": "tutorbot",
                                "bot_id": bot_id,
                                "channel": msg.channel,
                                "chat_id": msg.chat_id,
                            },
                        )
                    )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Outbound router failed for bot %s", bot_id)

    async def stop_bot(self, bot_id: str, *, preserve_auto_start: bool = False) -> bool:
        """Stop a running TutorBot instance.

        Manual stops should disable future auto-starts, but process shutdown
        must preserve the persisted auto-start intent so Docker/host restarts
        bring the same bots back online.
        """
        instance = self._bots.get(bot_id)
        if not instance:
            return False
        auto_start = self._load_auto_start(bot_id, default=True) if preserve_auto_start else False

        import os
        if os.getenv("REDIS_URL"):
            await self._bot_process_manager.stop(bot_id)

        for task in instance.tasks:
            if not task.done():
                task.cancel()
        for task in instance.tasks:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if instance.channel_manager:
            try:
                await instance.channel_manager.stop_all()
            except Exception:
                logger.exception("Error stopping channels for bot '%s'", bot_id)

        if instance.heartbeat:
            instance.heartbeat.stop()

        if instance.agent_loop:
            try:
                await instance.agent_loop.stop()
            except Exception:
                pass

        self.save_bot_config(bot_id, instance.config, auto_start=auto_start)
        del self._bots[bot_id]
        logger.info(
            "TutorBot '%s' stopped (auto_start=%s, preserve_auto_start=%s)",
            bot_id,
            auto_start,
            preserve_auto_start,
        )
        return True

    def _build_channel_manager(
        self,
        config: BotConfig,
        bus: Any,
        *,
        bot_id: str,
    ) -> Any | None:
        """Construct a ``ChannelManager`` from ``config.channels`` or return ``None``.

        Centralised so ``start_bot`` and ``reload_channels`` produce identical
        behaviour. Raises ``pydantic.ValidationError`` if the channels dict is
        malformed; callers decide whether to swallow or propagate.
        """
        if not config.channels:
            return None
        from deeptutor.tutorbot.channels.manager import ChannelManager
        from deeptutor.tutorbot.config.schema import ChannelsConfig

        channels_config = ChannelsConfig(**config.channels)
        manager = ChannelManager(channels_config, bus)
        if not manager.channels:
            logger.info("No channels matched config for bot '%s'", bot_id)
            return None
        logger.info(
            "Channels enabled for bot '%s': %s",
            bot_id,
            list(manager.channels.keys()),
        )
        return manager

    async def reload_channels(self, bot_id: str) -> None:
        """Restart channel listeners from ``instance.config.channels`` (same MessageBus).

        Cancels only ``tutorbot:{bot_id}:ch:*`` tasks; agent loop and outbound
        router keep running. Concurrent invocations on the same bot are
        serialised via ``instance.reload_lock`` to avoid duplicate listeners.

        On success, ``instance.last_reload_error`` is cleared. On failure, the
        listeners are torn down (bot is left running with no channels) and the
        error is recorded; callers should surface it to the user.
        """
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            return

        async with instance.reload_lock:
            await self._teardown_channel_listeners(instance, bot_id)

            try:
                _bus = instance.bus or (instance.agent_loop.bus if instance.agent_loop else None)
                channel_manager = self._build_channel_manager(
                    instance.config,
                    _bus,
                    bot_id=bot_id,
                )
            except Exception as exc:
                logger.exception("Failed to reload channels for bot '%s'", bot_id)
                instance.channel_manager = None
                instance.last_reload_error = f"{type(exc).__name__}: {exc}"
                raise

            instance.channel_manager = channel_manager
            instance.last_reload_error = None
            if channel_manager:
                for ch_name, ch in channel_manager.channels.items():
                    ch_task = asyncio.create_task(
                        ch.start(),
                        name=f"tutorbot:{bot_id}:ch:{ch_name}",
                    )
                    instance.tasks.append(ch_task)
                logger.info(
                    "Reloaded channels for bot '%s': %s",
                    bot_id,
                    list(channel_manager.channels.keys()),
                )

    async def _teardown_channel_listeners(
        self,
        instance: TutorBotInstance,
        bot_id: str,
    ) -> None:
        """Cancel ``tutorbot:{bot_id}:ch:*`` tasks and stop the existing manager.

        Note: ``channel_bindings`` are intentionally cleared — they map
        channel→last-seen chat_id and will be rebuilt as the rebooted listeners
        receive new traffic. Pending heartbeat replies bound to a stale chat_id
        will be dropped (acceptable: same behaviour as Stop/Start).
        """
        ch_prefix = f"tutorbot:{bot_id}:ch:"
        to_remove = [t for t in instance.tasks if (t.get_name() or "").startswith(ch_prefix)]
        for t in to_remove:
            if not t.done():
                t.cancel()
        for t in to_remove:
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        instance.tasks = [t for t in instance.tasks if t not in to_remove]

        if instance.channel_manager:
            try:
                await instance.channel_manager.stop_all()
            except Exception:
                logger.exception("Error stopping channels before reload for bot '%s'", bot_id)

        instance.channel_manager = None
        instance.channel_bindings.clear()

    # ── Listing & discovery ───────────────────────────────────────

    def _discover_bot_ids(self) -> set[str]:
        """Return all bot IDs found on disk."""
        ids: set[str] = set()
        if not self._tutorbot_dir.exists():
            return ids

        for entry in self._tutorbot_dir.iterdir():
            if entry.name in _RESERVED_NAMES:
                continue
            if entry.is_dir() and (entry / "config.yaml").exists():
                ids.add(entry.name)
        return ids

    def list_bots(self) -> list[dict[str, Any]]:
        """List all known bots (running + configured on disk).

        Channel field is keys-only — never expose secrets via the list endpoint.
        """
        result: dict[str, dict[str, Any]] = {}

        for bot_id, inst in self._bots.items():
            result[bot_id] = inst.to_dict()

        for bid in self._discover_bot_ids():
            if bid in result:
                continue
            self._maybe_migrate_legacy(bid)
            cfg = self.load_bot_config(bid)
            result[bid] = {
                "bot_id": bid,
                "name": cfg.name if cfg else bid,
                "description": cfg.description if cfg else "",
                "persona": cfg.persona if cfg else "",
                "channels": list(cfg.channels.keys()) if cfg else [],
                "model": cfg.model if cfg else None,
                "llm_selection": cfg.llm_selection if cfg else None,
                "running": False,
                "started_at": None,
            }

        return list(result.values())

    def get_bot(self, bot_id: str) -> TutorBotInstance | None:
        return self._bots.get(bot_id)

    def get_bot_history(
        self,
        bot_id: str,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read chat messages from one bot session JSONL.

        When ``session_id`` is None, resolves to the bot's current default
        session (backward-compatible behaviour for the legacy /history route).
        """
        sessions_dir = self._bot_workspace(bot_id) / "sessions"
        if not sessions_dir.exists():
            return []

        if session_id is None:
            from deeptutor.tutorbot.session.manager import SessionManager as _SM
            default = _SM(self._bot_workspace(bot_id)).ensure_default_session(bot_id)
            session_id = default.key.split(":s:")[-1]

        # The on-disk filename comes from SessionManager._get_session_path,
        # which slugifies the full key `bot:<id>:s:<sid>` → `bot_<id>_s_<sid>`
        # (double `s_` when the sid itself starts with `s_`, which ours do).
        from deeptutor.tutorbot.session.manager import SessionManager as _SM
        sm_path = _SM(self._bot_workspace(bot_id))
        path = sm_path._get_session_path(f"bot:{bot_id}:s:{session_id}")
        if not path.exists():
            return []

        indexed_messages: list[tuple[float, int, dict[str, Any]]] = []
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
                        raw_content = data["content"]
                        if data.get("role") == "user":
                            text, attachments = _extract_attachments_and_clean_content(raw_content)
                            data["content"] = text
                            if attachments:
                                data["attachments"] = attachments
                        else:
                            data["content"] = normalize_message_content(raw_content)
                        data.pop("reasoning_content", None)
                        indexed_messages.append(
                            (_history_sort_timestamp(data, file_mtime), sequence, data)
                        )
                        sequence += 1
        except Exception:
            return []

        indexed_messages.sort(key=lambda item: (item[0], item[1]))
        messages = [item[2] for item in indexed_messages]
        return messages[-limit:]

    def list_sessions(self, bot_id: str) -> list[dict[str, Any]]:
        """Return session rows for the sidebar: default first, then updated_at desc."""
        from deeptutor.tutorbot.session.manager import SessionManager as _SM

        workspace = self._bot_workspace(bot_id)
        sm = _SM(workspace)
        sm.ensure_default_session(bot_id)

        out: list[dict[str, Any]] = []
        for row in sm.list_for_bot(bot_id):
            sid = row["id"]
            path = sm._get_session_path(f"bot:{bot_id}:s:{sid}")
            out.append({
                "id": sid,
                "title": row["title"],
                "title_source": row["title_source"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "has_user_messages": _has_user_message(path),
                "lesson_plan_brief": _lesson_brief(row.get("lesson_plan")),
            })
        return out

    def create_session(self, bot_id: str) -> dict[str, Any]:
        """M3: promote the current default (status=completed) and allocate a new default.

        409 with {existing_default_id} when the current default has no user messages.
        """
        from fastapi import HTTPException

        from deeptutor.tutorbot.session.manager import SessionManager as _SM

        workspace = self._bot_workspace(bot_id)
        sm = _SM(workspace)
        default = sm.ensure_default_session(bot_id)

        has_user_msg = any(m.get("role") == "user" and m.get("content") for m in default.messages)
        if not has_user_msg:
            existing_id = default.key.split(":s:")[-1]
            raise HTTPException(
                status_code=409, detail={"existing_default_id": existing_id},
            )

        _, new_default = sm.promote_default(
            default, title="", title_source="manual", completed=True,
        )
        assert new_default is not None
        return {
            "id": new_default.key.split(":s:")[-1],
            "title": "",
            "title_source": None,
            "status": "default",
            "updated_at": new_default.updated_at.isoformat(),
            "has_user_messages": False,
            "lesson_plan_brief": None,
        }

    def get_tree(self) -> list[dict[str, Any]]:
        """Whole sidebar tree: every discovered bot + its sessions."""
        out: list[dict[str, Any]] = []
        for bid in self._discover_bot_ids():
            cfg = self.load_bot_config(bid)
            instance = self._bots.get(bid)
            out.append({
                "bot_id": bid,
                "name": cfg.name if cfg else bid,
                "running": bool(instance and instance.running),
                "sessions": self.list_sessions(bid),
            })
        return out

    def get_recent_active_bots(self, limit: int = 3) -> list[dict[str, Any]]:
        """Return the most recently active bots with their last message preview."""
        bot_activity: list[tuple[float, str, dict[str, Any]]] = []

        for bid in self._discover_bot_ids():
            sessions_dir = self._bot_workspace(bid) / "sessions"
            if not sessions_dir.is_dir():
                continue

            jsonl_files = list(sessions_dir.glob("*.jsonl"))
            if not jsonl_files:
                continue

            newest = max(jsonl_files, key=lambda p: p.stat().st_mtime)
            mtime = newest.stat().st_mtime

            last_msg = ""
            try:
                with open(newest, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("_type") == "metadata":
                            continue
                        if data.get("role") in ("user", "assistant") and data.get("content"):
                            last_msg = normalize_message_content(data["content"])
            except Exception:
                pass

            cfg = self.load_bot_config(bid)
            instance = self._bots.get(bid)
            bot_activity.append(
                (
                    mtime,
                    bid,
                    {
                        "bot_id": bid,
                        "name": cfg.name if cfg else bid,
                        "running": instance.running if instance else False,
                        "last_message": last_msg[:200] if last_msg else "",
                        "updated_at": datetime.fromtimestamp(mtime).isoformat(),
                    },
                )
            )

        bot_activity.sort(key=lambda x: x[0], reverse=True)
        return [item[2] for item in bot_activity[:limit]]

    async def send_message(
        self,
        bot_id: str,
        content: str,
        chat_id: str = "web",
        session_id: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_lesson_update: Callable[[dict], Awaitable[None]] | None = None,
        on_session_promoted: Callable[[dict, dict], Awaitable[None]] | None = None,
        attachments: list[dict] | None = None,
    ) -> str:
        """Send a message to a running bot and return the response.

        Args:
            bot_id: The bot to message.
            content: The user's text message.
            chat_id: Chat identifier (default "web").
            session_id: Optional explicit session ID.
            on_progress: Optional streaming progress callback.
            on_lesson_update: Optional lesson-plan update callback.
            on_session_promoted: Optional session-promotion callback.
            attachments: Wire-format attachment dicts from the WebSocket
                frontend.  Each dict has the shape
                ``{"type": "image"|"audio", "base64": "...",
                "mime_type": "...", "filename": "..."}``.
                Channel adapters (matrix, wecom, etc.) leave this as
                ``None`` — the existing path-based media flow is used.
        """
        instance = self._bots.get(bot_id)
        if not instance or not instance.running:
            raise RuntimeError(f"Bot '{bot_id}' is not running")

        if session_id is None:
            default = instance.agent_loop.sessions.ensure_default_session(bot_id)
            session_id = default.key.split(":s:")[-1]

        canonical_key = f"bot:{bot_id}:s:{session_id}"

        # Bridge the per-turn promotion callback into the agent loop, which
        # will pass it to lesson tools via set_session_accessor.
        if on_session_promoted is not None:
            loop = asyncio.get_running_loop()

            def _bridge(promoted_key: str, new_default_key: str | None) -> None:
                async def _emit() -> None:
                    sm = instance.agent_loop.sessions
                    promoted = sm.get_or_create(promoted_key)
                    promoted_view = {
                        "id": promoted_key.split(":s:")[-1],
                        "title": promoted.metadata.get("title", ""),
                        "title_source": promoted.metadata.get("title_source"),
                        "lesson_plan_brief": _lesson_brief(promoted.metadata.get("lesson_plan")),
                    }
                    new_default_view: dict = {}
                    if new_default_key:
                        new_default_view = {
                            "id": new_default_key.split(":s:")[-1],
                            "title": "",
                            "status": "default",
                        }
                    try:
                        await on_session_promoted(promoted_view, new_default_view)
                    except Exception:
                        logger.exception("on_session_promoted callback raised")
                loop.create_task(_emit())

            instance.agent_loop.set_session_promoted_callback(_bridge)
        else:
            instance.agent_loop.set_session_promoted_callback(None)

        async def _progress(text: str, *, tool_hint: bool = False, delta: bool = False) -> None:
            if on_progress:
                try:
                    await on_progress(text, tool_hint=tool_hint, delta=delta)
                except TypeError:
                    # Older callers don't accept the kwargs — fall back to
                    # text-only so streaming still degrades gracefully.
                    await on_progress(text)

        response = await instance.agent_loop.process_direct(
            content,
            session_key=canonical_key,
            channel="web",
            chat_id=chat_id,
            on_progress=_progress,
            on_lesson_update=on_lesson_update,
            attachments=attachments or None,
        )

        # Forward the reply to any bound external channels so mobile users
        # see the web-originated conversation in their chat app.
        if instance.channel_manager and response:
            from deeptutor.tutorbot.bus.events import OutboundMessage

            for ch_name, ch_chat_id in instance.channel_bindings.items():
                ch = instance.channel_manager.get_channel(ch_name)
                if ch:
                    try:
                        await ch.send(
                            OutboundMessage(
                                channel=ch_name,
                                chat_id=ch_chat_id,
                                content=response,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Failed to forward web reply to channel %s for bot %s",
                            ch_name,
                            bot_id,
                        )

        return response

    async def auto_start_bots(self) -> None:
        """Scan persisted configs and start bots marked with auto_start: true."""
        for bid in self._discover_bot_ids():
            if bid in self._bots and self._bots[bid].running:
                continue
            try:
                self._maybe_migrate_legacy(bid)
                path = self._bot_dir(bid) / "config.yaml"
                if not path.exists():
                    continue
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not data.get("auto_start", False):
                    continue
                config = BotConfig(
                    name=data.get("name", bid),
                    description=data.get("description", ""),
                    persona=data.get("persona", ""),
                    channels=data.get("channels", {}),
                    model=data.get("model"),
                    llm_selection=data.get("llm_selection"),
                )
                await self.start_bot(bid, config)
                logger.info("Auto-started bot '%s'", bid)
            except Exception:
                logger.exception("Failed to auto-start bot '%s'", bid)

    async def destroy_bot(self, bot_id: str) -> bool:
        """Stop a bot (if running) and permanently delete its data from disk."""
        await self.stop_bot(bot_id, preserve_auto_start=False)
        bot_dir = self._bot_dir(bot_id)
        if not bot_dir.exists():
            return False
        shutil.rmtree(bot_dir)
        logger.info("TutorBot '%s' destroyed (data deleted)", bot_id)
        return True

    # ── Workspace file helpers ────────────────────────────────────

    _EDITABLE_FILES = {"SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md", "HEARTBEAT.md"}

    def read_bot_file(self, bot_id: str, filename: str) -> str | None:
        if filename not in self._EDITABLE_FILES:
            return None
        path = self._bot_workspace(bot_id) / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_bot_file(self, bot_id: str, filename: str, content: str) -> bool:
        if filename not in self._EDITABLE_FILES:
            return False
        path = self._bot_workspace(bot_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    def read_all_bot_files(self, bot_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        ws = self._bot_workspace(bot_id)
        for fn in self._EDITABLE_FILES:
            path = ws / fn
            result[fn] = path.read_text(encoding="utf-8") if path.exists() else ""
        return result

    async def stop_all(self, *, preserve_auto_start: bool = True) -> None:
        """Stop all running bots while preserving restart intent by default.

        Iterates dict keys directly to avoid needing per-user context at shutdown.
        The on-disk config (including auto_start) is already persisted from the
        last save_bot_config call, so skipping the save here IS preserve_auto_start.
        """
        for key in list(self._bots.keys()):
            instance = self._bots.pop(key, None)
            if instance is None:
                continue
            bot_id = instance.bot_id
            for task in instance.tasks:
                if not task.done():
                    task.cancel()
            for task in instance.tasks:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            if instance.channel_manager:
                try:
                    await instance.channel_manager.stop_all()
                except Exception:
                    logger.exception("Error stopping channels for bot '%s'", bot_id)
            if instance.heartbeat:
                instance.heartbeat.stop()
            if instance.agent_loop:
                try:
                    await instance.agent_loop.stop()
                except Exception:
                    pass
            logger.info("TutorBot '%s' stopped (shutdown)", bot_id)

    # ── Soul template library ─────────────────────────────────────

    def _load_builtin_souls(self) -> list[dict[str, str]]:
        path = self._builtin_souls_file()
        if not path.exists():
            logger.warning("Builtin souls file missing: %s", path)
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return data if isinstance(data, list) else []

    def _load_user_souls(self) -> list[dict[str, str]]:
        path = self._user_souls_file
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return data if isinstance(data, list) else []

    def _save_user_souls(self, souls: list[dict[str, str]]) -> None:
        self._tutorbot_dir.mkdir(parents=True, exist_ok=True)
        self._user_souls_file.write_text(
            yaml.dump(souls, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    def list_souls(self) -> list[dict]:
        by_id: dict[str, dict] = {}
        for soul in self._load_builtin_souls():
            by_id[soul["id"]] = {**soul, "source": "builtin", "editable": False}
        for soul in self._load_user_souls():
            by_id[soul["id"]] = {**soul, "source": "user", "editable": True}
        return list(by_id.values())

    def get_soul(self, soul_id: str) -> dict | None:
        for s in self.list_souls():
            if s["id"] == soul_id:
                return s
        return None

    def create_soul(self, soul_id: str, name: str, content: str) -> dict:
        """Create or override a soul in the user's _souls.yaml."""
        user_souls = self._load_user_souls()
        entry = {"id": soul_id, "name": name, "content": content}
        user_souls = [s for s in user_souls if s.get("id") != soul_id] + [entry]
        self._save_user_souls(user_souls)
        return {**entry, "source": "user", "editable": True}

    def update_soul(self, soul_id: str, name: str | None, content: str | None) -> dict | None:
        user_souls = self._load_user_souls()
        for s in user_souls:
            if s.get("id") == soul_id:
                if name is not None:
                    s["name"] = name
                if content is not None:
                    s["content"] = content
                self._save_user_souls(user_souls)
                return {**s, "source": "user", "editable": True}
        for s in self._load_builtin_souls():
            if s.get("id") == soul_id:
                new = dict(s)
                if name is not None:
                    new["name"] = name
                if content is not None:
                    new["content"] = content
                user_souls.append(new)
                self._save_user_souls(user_souls)
                return {**new, "source": "user", "editable": True}
        return None

    def delete_soul(self, soul_id: str) -> bool:
        user_souls = self._load_user_souls()
        new = [s for s in user_souls if s.get("id") != soul_id]
        if len(new) == len(user_souls):
            return False
        self._save_user_souls(new)
        return True


_managers: dict[str, TutorBotManager] = {}


def get_tutorbot_manager() -> TutorBotManager:
    """Return the TutorBotManager for the current user, cached by user.id."""
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    mgr = _managers.get(user.id)
    if mgr is None:
        mgr = TutorBotManager(scope=user.scope)
        _managers[user.id] = mgr
    return mgr


def shutdown_all_managers() -> None:
    """Used at process shutdown to stop bots across every cached manager."""
    for mgr in list(_managers.values()):
        for bot_id in list(mgr._bots):
            try:
                instance = mgr._bots.pop(bot_id, None)
                if instance and instance.heartbeat:
                    instance.heartbeat.stop()
            except Exception:
                pass
