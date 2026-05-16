"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from deeptutor.tutorbot.agent.context import ContextBuilder
from deeptutor.tutorbot.agent.memory import MemoryConsolidator
from deeptutor.tutorbot.agent.subagent import SubagentManager
from deeptutor.tutorbot.agent.team import TeamManager
from deeptutor.tutorbot.agent.team.tools import TeamTool
from deeptutor.tutorbot.agent.tools.cron import CronTool
from deeptutor.tutorbot.agent.tools.message import MessageTool
from deeptutor.tutorbot.agent.tools.registry import DIRECT_RESULT_PREFIX as _DIRECT_RESULT_PREFIX, ToolRegistry, build_base_tools
from deeptutor.tutorbot.agent.tools.spawn import SpawnTool
from deeptutor.tutorbot.bus.events import InboundMessage, OutboundMessage
from deeptutor.tutorbot.bus.queue import MessageBus
from deeptutor.tutorbot.providers.base import LLMProvider
from deeptutor.tutorbot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from deeptutor.tutorbot.config.schema import ChannelsConfig, ExecToolConfig, WebSearchConfig
    from deeptutor.tutorbot.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        team_max_workers: int = 5,
        team_worker_max_iterations: int = 25,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        shared_memory_dir: Path | None = None,
        default_session_key: str | None = None,
    ):
        from deeptutor.tutorbot.config.schema import ExecToolConfig, WebSearchConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.context_window_tokens = context_window_tokens
        self.web_search_config = web_search_config or WebSearchConfig()
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self._shared_memory_dir = shared_memory_dir
        self._default_session_key = default_session_key

        self.context = ContextBuilder(workspace, shared_memory_dir=shared_memory_dir)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            web_search_config=self.web_search_config,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        self.team = TeamManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            sessions=self.sessions,
            model=self.model,
            temperature=provider.generation.temperature,
            max_tokens=provider.generation.max_tokens,
            reasoning_effort=provider.generation.reasoning_effort,
            web_search_config=self.web_search_config,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            max_workers=team_max_workers,
            worker_max_iterations=team_worker_max_iterations,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._processing_lock = asyncio.Lock()
        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            shared_memory_dir=shared_memory_dir,
        )
        self._register_default_tools()

    def update_llm(
        self,
        *,
        provider: LLMProvider,
        model: str | None = None,
        context_window_tokens: int | None = None,
    ) -> None:
        """Swap the provider/model used by future TutorBot turns."""
        self.provider = provider
        self.model = model or provider.get_default_model()
        if context_window_tokens:
            self.context_window_tokens = context_window_tokens

        self.subagents.provider = provider
        self.subagents.model = self.model

        self.team.provider = provider
        self.team.model = self.model
        self.team.temperature = provider.generation.temperature
        self.team.max_tokens = provider.generation.max_tokens
        self.team.reasoning_effort = provider.generation.reasoning_effort

        self.memory_consolidator.provider = provider
        self.memory_consolidator.model = self.model
        if context_window_tokens:
            self.memory_consolidator.context_window_tokens = context_window_tokens

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        self.tools = build_base_tools(
            workspace=self.workspace,
            exec_config=self.exec_config,
            web_search_config=self.web_search_config,
            web_proxy=self.web_proxy,
            restrict_to_workspace=self.restrict_to_workspace,
        )
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        # NOTE: TeamTool intentionally not registered for the default tutorbot.
        # It competes with plan_lesson for the "structure a multi-step task"
        # mind-share and LLMs preferentially pick it even for pure teaching
        # prompts. Users who genuinely want multi-agent orchestration can
        # still trigger it via the `/team <goal>` slash command (handled in
        # _process_message), which preserves the feature without polluting
        # the LLM's tool schema.
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        from deeptutor.tutorbot.agent.tools.deeptutor_tools import (
            BrainstormAdapterTool,
            CodeExecutionAdapterTool,
            PaperSearchAdapterTool,
            RAGAdapterTool,
            ReasonAdapterTool,
            VisualizeAdapterTool,
        )
        from deeptutor.tutorbot.agent.tools.lesson import (
            CompleteStepTool,
            InsertStepTool,
            PlanLessonTool,
        )

        for tool_cls in (
            BrainstormAdapterTool,
            RAGAdapterTool,
            CodeExecutionAdapterTool,
            ReasonAdapterTool,
            PaperSearchAdapterTool,
            VisualizeAdapterTool,
            PlanLessonTool,
            CompleteStepTool,
            InsertStepTool,
        ):
            self.tools.register(tool_cls())

        # Log the registered tool set once at boot so it is easy to see
        # from the backend log whether plan_lesson/complete_step are present.
        logger.info(
            "Tutorbot tools registered: {}",
            sorted(self.tools.tool_names),
        )

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from deeptutor.tutorbot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except BaseException as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception as close_error:
                    logger.debug("Failed to close MCP stack cleanly: {}", close_error)
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron", "team"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    def _set_lesson_session_accessor(
        self,
        session_getter,
        on_update=None,
    ) -> None:
        """Point the lesson tools at the active session and live-update hook."""
        for name in ("plan_lesson", "complete_step", "insert_step"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_session_accessor"):
                    tool.set_session_accessor(session_getter, on_update)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""

        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'

        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _llm_call_with_keepalive(
        self,
        *,
        messages: list[dict],
        tool_defs: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None,
    ):
        """Call the LLM, streaming deltas to ``on_progress`` and emitting a
        keepalive ping if the model produces nothing for >8 s.

        Returns ``(response, streamed_any)``. ``streamed_any`` is True when at
        least one delta was forwarded — callers use it to skip re-emitting
        the same preamble after the call returns.
        """
        if on_progress is None:
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tool_defs,
                model=self.model,
            )
            return response, False

        delta_seen = asyncio.Event()
        buf: list[str] = []
        last_flush = [time.monotonic()]
        flush_lock = asyncio.Lock()
        streamed_any = [False]

        _FLUSH_BYTES = 200
        _FLUSH_INTERVAL_S = 0.12
        _KEEPALIVE_INTERVAL_S = 8.0

        async def _flush() -> None:
            async with flush_lock:
                if not buf:
                    return
                text = "".join(buf)
                buf.clear()
                last_flush[0] = time.monotonic()
                streamed_any[0] = True
                try:
                    await on_progress(text, delta=True)
                except TypeError:
                    # on_progress doesn't accept the kwarg — degrade gracefully.
                    try:
                        await on_progress(text)
                    except Exception:
                        pass
                except Exception:
                    pass

        async def _on_reasoning_delta(text: str) -> None:
            """Reasoning tokens → thinking panel (streamed live)."""
            if not text:
                return
            delta_seen.set()
            buf.append(text)
            total = sum(len(s) for s in buf)
            if total >= _FLUSH_BYTES or (time.monotonic() - last_flush[0]) >= _FLUSH_INTERVAL_S:
                await _flush()

        async def _on_content_delta(text: str) -> None:
            """Content tokens: suppress keepalive ping but do NOT stream to
            the thinking panel.  The assembled response.content is emitted as
            the final CONTENT event — streaming it here would duplicate the
            response text inside the thinking panel."""
            if text:
                delta_seen.set()

        async def _keepalive() -> None:
            # Wait for either a delta or the keepalive interval. As soon as
            # the model emits anything, the stream itself is the progress
            # signal — no synthetic ping needed.
            try:
                while not delta_seen.is_set():
                    try:
                        await asyncio.wait_for(
                            delta_seen.wait(),
                            timeout=_KEEPALIVE_INTERVAL_S,
                        )
                        return
                    except asyncio.TimeoutError:
                        try:
                            await on_progress("Thinking…")
                        except Exception:
                            pass
            except asyncio.CancelledError:
                raise

        keepalive_task = asyncio.create_task(_keepalive())
        try:
            response = await self.provider.chat_stream_with_retry(
                messages=messages,
                tools=tool_defs,
                model=self.model,
                on_content_delta=_on_content_delta,
                on_reasoning_delta=_on_reasoning_delta,
            )
        finally:
            keepalive_task.cancel()
            try:
                await _flush()
            except Exception:
                pass
        return response, streamed_any[0]

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict], bool]:
        """Run the agent iteration loop.

        Returns ``(final_content, tools_used, messages, had_direct_result)``.
        ``had_direct_result`` is True when a tool returned a
        ``DIRECT_RESULT_PREFIX``-marked payload — that payload IS the
        user-facing response and must override any earlier ``message()``
        side-effects.
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        had_direct_result = False
        # Count consecutive same-tool failures within this turn. The LLM
        # sometimes locks onto a tool that's intermittently broken (e.g.
        # `visualize` codegen returning empty on certain physics prompts)
        # and retries it 5+ times, eating minutes. After MAX_SAME_TOOL_FAILS
        # consecutive errors for the same tool, we force-stop the loop and
        # let the parent emit text instead.
        _MAX_SAME_TOOL_FAILS = 3
        last_failed_tool: str | None = None
        same_tool_fail_count = 0
        # Accumulate substantive assistant text across iterations. When the
        # model emits prose alongside a tool call (e.g. the actual lesson
        # body before `complete_step`), that text MUST end up in the user-
        # visible reply — sending it only as `thinking` (collapsible) loses
        # the explanation the model intended to show.
        visible_parts: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            tool_defs = self.tools.get_definitions()
            _last_user_preview = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    c = m.get("content")
                    _last_user_preview = (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))[:200]
                    break
            logger.warning(
                "LLM request: iter={} msgs={} tools={} last_user={!r}",
                iteration, len(messages), len(tool_defs), _last_user_preview,
            )

            response, streamed_any = await self._llm_call_with_keepalive(
                messages=messages,
                tool_defs=tool_defs,
                on_progress=on_progress,
            )

            logger.warning(
                "LLM response: iter={} content_len={} tool_calls={} reasoning_len={} finish={!r} content_preview={!r}",
                iteration,
                len(response.content or ""),
                [tc.name for tc in (response.tool_calls or [])],
                len(response.reasoning_content or ""),
                response.finish_reason,
                (response.content or "")[:200],
            )

            if response.has_tool_calls:
                thought = self._strip_think(response.content)
                if thought:
                    visible_parts.append(thought)
                if on_progress:
                    # Avoid double-emitting the preamble: if we already
                    # streamed deltas to the user, the thought is already
                    # visible in the rolling thinking buffer.
                    if thought and not streamed_any:
                        await on_progress(thought)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                _TOOL_TIMEOUT = 180  # default seconds — fast-fail on hangs
                _TOOL_TIMEOUT_OVERRIDES: dict[str, int] = {
                    # visualize runs codegen with reasoning_effort=low + one
                    # retry on empty output. Each LLM call typically lands in
                    # 30–90s; 180s covers two slow attempts plus buffer. If
                    # the model is fully stuck (no streamed bytes), the
                    # surrounding timeout bail-out kicks in here rather than
                    # letting the parent agent wait minutes for nothing.
                    "visualize": 180,
                }
                _KEEPALIVE_INTERVAL = 8  # seconds between progress pings

                direct_result: str | None = None
                had_tool_timeout = False
                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])

                    # Keep the client's "thinking" spinner alive during long tool calls
                    # (e.g. multi-stage LLM pipelines that hold the event loop for 60–90 s).
                    async def _keepalive(name: str = tool_call.name) -> None:
                        await asyncio.sleep(_KEEPALIVE_INTERVAL)
                        while True:
                            if on_progress:
                                try:
                                    await on_progress(f"Working on {name}…")
                                except Exception:
                                    pass
                            await asyncio.sleep(_KEEPALIVE_INTERVAL)

                    keepalive_task = asyncio.create_task(_keepalive())
                    _this_timeout = _TOOL_TIMEOUT_OVERRIDES.get(tool_call.name, _TOOL_TIMEOUT)
                    try:
                        result = await asyncio.wait_for(
                            self.tools.execute(tool_call.name, tool_call.arguments),
                            timeout=_this_timeout,
                        )
                    except asyncio.TimeoutError:
                        result = f"Error: tool '{tool_call.name}' timed out after {_this_timeout}s."
                        had_tool_timeout = True
                    finally:
                        keepalive_task.cancel()

                    if result.startswith(_DIRECT_RESULT_PREFIX):
                        direct_result = result[len(_DIRECT_RESULT_PREFIX):]
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name, direct_result
                        )
                        # Successful direct-result resets the per-tool failure
                        # counter so unrelated future failures aren't penalised.
                        last_failed_tool = None
                        same_tool_fail_count = 0
                        break
                    # Track consecutive failures by tool name so we can break
                    # out of LLM-driven retry loops that aren't converging.
                    if isinstance(result, str) and result.startswith("Error"):
                        if last_failed_tool == tool_call.name:
                            same_tool_fail_count += 1
                        else:
                            last_failed_tool = tool_call.name
                            same_tool_fail_count = 1
                    else:
                        last_failed_tool = None
                        same_tool_fail_count = 0
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                if direct_result is not None:
                    had_direct_result = True
                    # If the model emitted substantive prose BEFORE the
                    # direct-result tool (e.g. a written walkthrough that the
                    # `visualize` figure illustrates), stitch it in front of
                    # the rendered payload — otherwise the user sees only the
                    # picture and loses the explanation that referenced it.
                    pre_text = "\n\n".join(p.strip() for p in visible_parts if p and p.strip())
                    if pre_text:
                        final_content = f"{pre_text}\n\n{direct_result}"
                    else:
                        final_content = direct_result
                    # Persist the direct result as the turn's assistant message
                    # so it survives in the session JSONL and shows up again on
                    # page reload (history endpoint filters by role+content and
                    # would otherwise drop the payload, which lives only on the
                    # tool message).
                    messages = self.context.add_assistant_message(
                        messages, direct_result
                    )
                    break
                # Bail out if the same tool has failed too many times this
                # turn — the LLM is stuck in a retry loop that's not making
                # progress. Surface a forced fallback message to the parent
                # LLM so the next iteration writes text instead.
                if same_tool_fail_count >= _MAX_SAME_TOOL_FAILS:
                    logger.warning(
                        "Tool {} failed {} times in a row this turn — forcing fallback",
                        last_failed_tool, same_tool_fail_count,
                    )
                    fallback_note = (
                        f"\n\n[SYSTEM] The `{last_failed_tool}` tool has failed "
                        f"{same_tool_fail_count} times this turn. STOP retrying it. "
                        f"Write a textual explanation instead — no more tool calls."
                    )
                    messages = self.context.add_assistant_message(
                        messages, fallback_note
                    )
                    same_tool_fail_count = 0
                    last_failed_tool = None
                    # Don't break — let the LLM produce its text response next iter.
                    continue
                if had_tool_timeout:
                    # Don't let the LLM cascade into more retries (e.g. swapping
                    # render_mode geometry → svg → html, each costing another
                    # full timeout). Surface control to the user; they can
                    # rephrase or ask for a different approach.
                    final_content = (
                        "I tried to use the tool but it timed out. "
                        "It might be temporarily slow or stuck. "
                        "Try rephrasing or ask for a simpler version."
                    )
                    messages = self.context.add_assistant_message(
                        messages, final_content
                    )
                    break
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages,
                    clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                if clean:
                    visible_parts.append(clean)
                # Stitch together everything the assistant said this turn —
                # the pre-tool-call prose plus the post-tool-call wrap-up.
                # Join with a paragraph break so consecutive chunks don't run
                # together visually.
                final_content = "\n\n".join(p.strip() for p in visible_parts if p and p.strip())
                if not final_content:
                    final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        logger.warning(
            "Agent turn complete: iters={} tools_used={} had_direct_result={} final_len={} preview={!r}",
            iteration, tools_used, had_direct_result, len(final_content or ""), (final_content or "")[:200],
        )
        return final_content, tools_used, messages, had_direct_result

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            cmd = msg.content.strip().lower()
            if cmd == "/stop":
                await self._handle_stop(msg)
            elif cmd == "/restart":
                await self._handle_restart(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)

                def _cleanup_task(
                    done_task: asyncio.Task[None],
                    session_key: str = msg.session_key,
                ) -> None:
                    session_tasks = self._active_tasks.get(session_key, [])
                    if done_task in session_tasks:
                        session_tasks.remove(done_task)

                task.add_done_callback(_cleanup_task)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        team_cancelled = await self.team.cancel_by_session(msg.session_key)
        if team_cancelled:
            session = self.sessions.get_or_create(msg.session_key)
            session.metadata.pop("nano_team_active", None)
            self.sessions.save(session)
        total = cancelled + sub_cancelled + team_cancelled
        content = f"Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
            )
        )

    async def _handle_restart(self, msg: InboundMessage) -> None:
        """Restart the process in-place via os.execv."""
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Restarting...",
            )
        )

        async def _do_restart():
            await asyncio.sleep(1)
            # Use original sys.argv to preserve entry point (tutorbot runs in-process)
            os.execv(sys.executable, [sys.executable] + sys.argv)  # nosec B606

        asyncio.create_task(_do_restart())

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="",
                            metadata=msg.metadata or {},
                        )
                    )
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Sorry, I encountered an error.",
                    )
                )

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_lesson_update: Callable[[dict], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            self._set_lesson_session_accessor(lambda s=session: s, on_lesson_update)
            history = session.get_history(max_messages=0)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
            )
            final_content, _, all_msgs, _ = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or self._default_session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        raw = msg.content.strip()
        cmd = raw.lower()
        if cmd == "/new":
            try:
                if not await self.memory_consolidator.archive_unconsolidated(session):
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Memory archival failed, session not cleared. Please try again.",
                    )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )

            session.clear()
            session.metadata.pop("nano_team_active", None)
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="New session started."
            )
        if cmd == "/help":
            lines = [
                "🐈 TutorBot commands:",
                "/new — Start a new conversation",
                "/stop — Stop the current task",
                "/restart — Restart the bot",
                "/team <goal> — Start or instruct nano team mode",
                "/team status — Show nano team state",
                "/team log [n] — Show detailed collaboration logs (default 20)",
                "/team approve <task_id> — Approve a pending task",
                "/team reject <task_id> <reason> — Reject a pending task",
                "/team manual <task_id> <instruction> — Send change request",
                "/team stop — Stop nano team mode",
                "/btw <instruction> — Async side task via single subagent",
                "/help — Show available commands",
            ]
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\n".join(lines),
            )
        current_message = msg.content
        if cmd.startswith("/btw"):
            arg = raw[4:].strip()
            if not arg:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Usage: /btw <instruction>",
                )
            started = await self.subagents.spawn(
                task=arg,
                label="btw",
                origin_channel=msg.channel,
                origin_chat_id=msg.chat_id,
                session_key=key,
            )
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=started)

        if cmd == "/team":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "Usage:\n"
                    "/team <goal>\n"
                    "/team status\n"
                    "/team log [n]\n"
                    "/team approve <task_id>\n"
                    "/team reject <task_id> <reason>\n"
                    "/team manual <task_id> <instruction>\n"
                    "/team stop"
                ),
            )

        if cmd.startswith("/teams "):
            cmd = "/team " + raw[7:].strip().lower()
            raw = "/team " + raw[7:].strip()

        if cmd.startswith("/team "):
            instruction = raw[6:].strip()
            parts = instruction.split(maxsplit=2)
            lowered = (parts[0] if parts else "").lower()
            if lowered == "status":
                content = self.team.status_text(key)
                session.metadata["nano_team_active"] = bool(self.team.has_unfinished_run(key))
                self.sessions.save(session)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata={"team_text": True},
                )
            if lowered == "log":
                n = 20
                if len(parts) > 1:
                    try:
                        n = max(1, min(200, int(parts[1])))
                    except (TypeError, ValueError):
                        n = 20
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=self.team.log_text(key, n=n),
                    metadata={"team_text": True},
                )
            if lowered == "stop":
                if msg.channel == "cli":
                    content = await self.team.stop_mode(key, with_snapshot=True)
                else:
                    content = await self.team.stop_mode(key)
                session.metadata.pop("nano_team_active", None)
                self.sessions.save(session)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata={"team_text": True},
                )
            if lowered == "approve":
                task_id = parts[1] if len(parts) > 1 else ""
                if not task_id:
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Usage: /team approve <task_id>",
                    )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=self.team.approve_for_session(key, task_id),
                    metadata={"team_text": True},
                )
            if lowered == "reject":
                task_id = parts[1] if len(parts) > 1 else ""
                reason = parts[2] if len(parts) > 2 else ""
                if not task_id or not reason.strip():
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Usage: /team reject <task_id> <reason>",
                    )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=self.team.reject_for_session(key, task_id, reason.strip()),
                    metadata={"team_text": True},
                )
            if lowered == "manual":
                task_id = parts[1] if len(parts) > 1 else ""
                instruction_text = parts[2] if len(parts) > 2 else ""
                if not task_id or not instruction_text.strip():
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Usage: /team manual <task_id> <instruction>",
                    )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=self.team.request_changes_for_session(
                        key, task_id, instruction_text.strip()
                    ),
                    metadata={"team_text": True},
                )

            content = await self.team.start_or_route_goal(key, instruction)
            session.metadata["nano_team_active"] = self.team.is_active(key)
            self.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
                metadata={"team_text": True},
            )

        if session.metadata.get("nano_team_active"):
            if not self.team.is_active(key):
                session.metadata.pop("nano_team_active", None)
                self.sessions.save(session)
            else:
                if msg.channel != "cli" and self.team.has_pending_approval(key):
                    approval_reply = self.team.handle_approval_reply(key, raw)
                    if approval_reply:
                        return OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=approval_reply,
                            metadata={"team_text": True},
                        )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "Team mode is active. Supported input:\n"
                        "- /team <instruction|status|log|approve|reject|manual|stop>\n"
                        "- /btw <instruction>"
                    ),
                )

        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        # Bind the lesson tools to this session so they can read/write metadata.
        self._set_lesson_session_accessor(lambda s=session: s, on_lesson_update)

        # Lesson-plan runtime injections. Two cases:
        #  (a) no plan AND user message looks like a teaching request → short
        #      urgent nudge to call plan_lesson FIRST. Placed right next to
        #      the student's message where the model can't ignore it.
        #  (b) plan is active AND the last assistant turn ended with a
        #      DIRECT_RESULT (e.g. visualize) → explicit "call complete_step
        #      first" hint so the LLM doesn't skip step closure.
        from deeptutor.tutorbot.agent.lesson import (
            detect_message_lang,
            load as _load_plan,
            looks_like_teaching_request,
            render_status_block,
        )

        history = session.get_history(max_messages=0)
        active_plan = _load_plan(session)

        # Localize the runtime nudges to match the student's writing language —
        # otherwise the English scaffolding pulls the model into English even
        # when the student is asking in Chinese.
        msg_lang = detect_message_lang(current_message)

        if active_plan is None and looks_like_teaching_request(current_message):
            if msg_lang == "zh":
                nudge = (
                    "[运行时提示——非学生输入]\n"
                    "这看起来是一次教学/讲解请求。本轮的第一次工具调用必须是 "
                    "`plan_lesson`，包含 3–6 个有序步骤。不要直接以自由文本作答，"
                    "也不要在 `plan_lesson` 之前调用 `visualize`。规划完成后，本轮"
                    "只执行其中一个步骤，然后调用 `complete_step` 并停止。\n"
                    "**请全程使用中文：思考过程、工具参数（含 `plan_lesson` 的 topic、"
                    "各步骤 goal、`complete_step` 的 output_summary 等）以及给学生看到"
                    "的回复，都必须是中文，不要用英文。**"
                )
                student_label = "学生消息"
            else:
                nudge = (
                    "[Runtime guidance — not student input]\n"
                    "This looks like a teaching / explanation request. Your FIRST tool "
                    "call this turn MUST be `plan_lesson` with 3–6 ordered steps. "
                    "Do NOT answer free-form. Do NOT call `visualize` before `plan_lesson`. "
                    "After planning, execute exactly ONE step this turn, then call "
                    "`complete_step` and stop."
                )
                student_label = "Student message"
            current_message = f"{nudge}\n\n---\n\n{student_label}:\n{current_message}"

        elif active_plan is not None:
            status = render_status_block(active_plan, lang=msg_lang)
            # Enforce the protocol: before `complete_step` fires, the assistant
            # must emit the step body as visible text. Otherwise the student
            # sees an empty turn and a wrap-up question that references content
            # they never saw.
            if msg_lang == "zh":
                step_body_hint = (
                    "\n\n**协议要求：在调用 `complete_step` 之前，你必须先用普通文本"
                    "把该步骤的讲解 / 提问内容完整发送出来——也就是学生本轮要在聊天框"
                    "里看到的实质内容（定义、例子、推导、问题等）。**\n"
                    "**思考（reasoning）不会被学生看到，所以不要把讲解只放在思考里。"
                    "如果在 `complete_step` 之前你的可见回复是空的或只有几个字，那就是"
                    "违反协议的 bug，必须先补上正文再调用工具。**"
                )
            else:
                step_body_hint = (
                    "\n\n**Protocol: BEFORE calling `complete_step`, emit the step's "
                    "body — definition, example, derivation, question, whatever the "
                    "step's goal calls for — as visible chat text. Reasoning / "
                    "thinking blocks are NOT shown to the student; if your visible "
                    "reply before `complete_step` is empty or trivial, that is a "
                    "protocol bug and you must produce the body first.**"
                )
            # Auto-resume hint: detect an in-progress step whose previous turn
            # likely ended with a DIRECT_RESULT (fenced code block from visualize).
            # Checked by inspecting the last assistant message in the persisted
            # history — if it starts with ``` we assume the step is mid-execution.
            resume_hint = ""
            current_step = active_plan.find(active_plan.current_step_id or "")
            if current_step and current_step.status == "in_progress":
                # Scan back through history for the last assistant message.
                last_assistant_text = ""
                for entry in reversed(history):
                    if entry.get("role") == "assistant" and entry.get("content"):
                        last_assistant_text = str(entry["content"])
                        break
                if last_assistant_text.lstrip().startswith("```"):
                    if msg_lang == "zh":
                        resume_hint = (
                            f"\n\n**上一轮你为步骤 `{current_step.id}` 输出了一张图。"
                            f"本轮的第一次工具调用必须是 "
                            f"`complete_step(id='{current_step.id}', "
                            f"output_summary='...')`，先把该步骤收尾，再开始下一步。**"
                        )
                    else:
                        resume_hint = (
                            f"\n\n**Your previous turn ended with a figure for step "
                            f"`{current_step.id}`. Your FIRST tool call this turn MUST "
                            f"be `complete_step(id='{current_step.id}', "
                            f"output_summary='...')` to close it out before starting "
                            f"the next step.**"
                        )
            student_label = "学生消息" if msg_lang == "zh" else "Student message"
            current_message = (
                f"{status}{resume_hint}{step_body_hint}\n\n---\n\n{student_label}:\n{current_message}"
            )

        # Universal language reminder: short messages like "小数和分数" don't
        # match the teaching-keyword heuristic above, so the heavier Chinese
        # nudge never fires and the model stays in English. Always inject a
        # short language directive when the student writes in Chinese — the
        # system-prompt Language policy alone isn't enough to override the
        # model's default English reasoning trace on terse inputs.
        if msg_lang == "zh" and "[运行时提示" not in current_message:
            current_message = (
                "[语言提示——非学生输入]\n"
                "学生使用中文。请用中文进行思考（thinking）、调用工具时传入的所有参数，"
                "以及给学生的最终回复——任何环节都不要使用英文。\n\n"
                "---\n\n"
                f"{current_message}"
            )

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        initial_messages = self.context.build_messages(
            history=history,
            current_message=current_message,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False, delta: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            meta["_delta"] = delta
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        final_content, _, all_msgs, had_direct_result = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        # A DIRECT_RESULT tool (e.g. `visualize`) produces the user-facing
        # response in `final_content` itself — it must override any earlier
        # message() side-effect the LLM batched in the same turn (e.g. a
        # "Let me draw that for you" chatty preamble), otherwise the rich
        # payload is lost and the user sees only the preamble.
        if (
            not had_direct_result
            and (mt := self.tools.get("message"))
            and isinstance(mt, MessageTool)
            and mt._sent_in_turn
        ):
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    @staticmethod
    def _strip_runtime_wrappers(text: str) -> str:
        """Peel off any of the per-turn nudges we prepend to user messages.

        The agent wraps the raw student message with:
          - the Runtime Context block (time/channel metadata)
          - the language-hint block ("[语言提示——非学生输入]" / "[Runtime guidance...")
          - the plan_lesson teaching nudge or lesson-status block
        Each section is separated from the next by ``\\n\\n---\\n\\n``. The
        actual student text appears after either a final ``学生消息:`` /
        ``Student message:`` label or the last ``---`` separator. Persisting
        the wrapped text into session history (and serving it back via
        /history) leaks the nudges into the user's chat bubble — strip them
        so the saved history shows only what the student actually typed.
        """
        if not text:
            return text
        # Strip the runtime-context preamble first (it's always at the top).
        if text.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
            head, sep, rest = text.partition("\n\n")
            if sep:
                text = rest
        # If a labelled student message exists, return the text after it.
        for label in ("学生消息:\n", "Student message:\n"):
            idx = text.rfind(label)
            if idx >= 0:
                return text[idx + len(label):].strip()
        # Otherwise, if any of the nudge sentinels appear, keep everything
        # after the LAST `---` separator.
        sentinels = (
            "[语言提示——非学生输入]",
            "[运行时提示——非学生输入]",
            "[Runtime guidance — not student input]",
            "# Current lesson:",
            "# 当前课程：",
        )
        if any(s in text for s in sentinels):
            tail = text.rsplit("\n\n---\n\n", 1)
            if len(tail) == 2 and tail[1].strip():
                return tail[1].strip()
        return text

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if (
                role == "tool"
                and isinstance(content, str)
                and len(content) > self._TOOL_RESULT_MAX_CHARS
            ):
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str):
                    stripped = self._strip_runtime_wrappers(content)
                    if not stripped:
                        continue
                    entry["content"] = stripped
                elif isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str):
                            stripped = self._strip_runtime_wrappers(c["text"])
                            if stripped:
                                filtered.append({"type": "text", "text": stripped})
                            continue
                        if c.get("type") == "image_url" and c.get("image_url", {}).get(
                            "url", ""
                        ).startswith("data:image/"):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_lesson_update: Callable[[dict], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg,
            session_key=session_key,
            on_progress=on_progress,
            on_lesson_update=on_lesson_update,
        )
        mt = self.tools.get("message")
        _mt_sent = isinstance(mt, MessageTool) and mt._sent_in_turn
        _mt_content = (mt._last_content if isinstance(mt, MessageTool) else None)

        if response is not None:
            return response.content or ""
        # When the agent used the message() tool, _process_message returns None but
        # the content was published to the bus (not consumed in this direct path).
        # Recover it from MessageTool so it reaches the WebSocket caller.
        if isinstance(mt, MessageTool):
            logger.debug(
                "process_direct: message tool _sent_in_turn={} _last_content_len={}",
                _mt_sent,
                len(_mt_content or ""),
            )
            if _mt_content is not None:
                return _mt_content
        return ""
