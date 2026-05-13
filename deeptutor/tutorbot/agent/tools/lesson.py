"""Lesson-planning tools: `plan_lesson` and `complete_step`.

These two tools let the LLM commit to and work through a structured multi-
step lesson plan. They mutate state on the current session and return
plain-string tool results — there is no DIRECT_RESULT magic here. The
"one-step-per-turn" invariant is enforced by:

  * `plan_lesson`'s result tells the LLM to execute only step 1 this turn.
  * `complete_step`'s result tells the LLM to stop and wait for the student.
  * The system prompt reinforces both.

If a step ends by calling `visualize` (which DOES short-circuit via
DIRECT_RESULT), the turn ends there and `complete_step` fires on the NEXT
user turn, before the LLM starts the next step. That's fine — each visual
lands as its own chat message, which is natural pedagogy.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from deeptutor.tutorbot.agent.lesson import (
    LessonPlan,
    LessonStep,
    complete,
    load,
    save,
)
from deeptutor.tutorbot.agent.tools.base import Tool
from deeptutor.tutorbot.session.manager import Session

_log = logging.getLogger(__name__)


class _SessionAwareTool(Tool):
    """Base for lesson tools — they need the active session."""

    def __init__(self) -> None:
        self._session_getter: Callable[[], Session | None] = lambda: None

    def set_session_accessor(self, getter: Callable[[], Session | None]) -> None:
        """Called by the agent loop at the start of each turn."""
        self._session_getter = getter

    def _session(self) -> Session | None:
        try:
            return self._session_getter()
        except Exception:
            return None


class PlanLessonTool(_SessionAwareTool):
    """Commit to a structured lesson plan for the current teaching turn."""

    @property
    def name(self) -> str:
        return "plan_lesson"

    @property
    def description(self) -> str:
        return (
            "**THE planning tool for teaching.** Call this ONCE at the start "
            "of any substantive teaching / explanation turn. This is NOT for "
            "delegating to sub-agents — it's for structuring YOUR OWN turn-by-"
            "turn lesson delivery.\n\n"
            "Prefer this over `team` for tutoring. `team` is for multi-agent "
            "orchestration of software tasks; `plan_lesson` is for pedagogy: "
            "breaking a teaching topic into 3–6 ordered steps, each picking a "
            "phase (assess / define / explain / check / adapt / wrap_up) and "
            "a short student-facing goal.\n\n"
            "After calling, execute ONLY step 1 this turn, then call "
            "`complete_step`, then STOP — let the student react before moving "
            "on. Do NOT call `plan_lesson` again until the student switches "
            "to a new topic."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What the student wants to learn, in their own words.",
                },
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "description": (
                        "Ordered lesson steps. Typical shape: "
                        "assess (optional) → define → explain (may use visualize) "
                        "→ check (quiz) → adapt (on wrong answer) → wrap_up."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Short stable id, e.g. 's1'.",
                            },
                            "phase": {
                                "type": "string",
                                "enum": [
                                    "assess",
                                    "define",
                                    "explain",
                                    "check",
                                    "adapt",
                                    "wrap_up",
                                ],
                            },
                            "goal": {
                                "type": "string",
                                "description": "One short sentence in the student's language.",
                            },
                            "requires": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Ids of steps that must finish first. Default empty.",
                            },
                            "tools_hint": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional advisory list, e.g. ['visualize'].",
                            },
                        },
                        "required": ["id", "phase", "goal"],
                    },
                },
            },
            "required": ["topic", "steps"],
        }

    async def execute(self, **kwargs: Any) -> str:  # type: ignore[override]
        session = self._session()
        if session is None:
            return "Error: plan_lesson requires an active session."

        try:
            steps = [LessonStep.model_validate(s) for s in kwargs.get("steps", [])]
            plan = LessonPlan(
                topic=str(kwargs.get("topic", "")).strip() or "untitled",
                steps=steps,
            )
        except Exception as exc:
            return f"Error: plan_lesson validation failed: {exc}"

        # Start on the first pending step.
        first = plan.first_pending()
        if first is None:
            return "Error: plan_lesson needs at least one pending step."
        first.status = "in_progress"
        plan.current_step_id = first.id
        save(session, plan)

        # Nudge the LLM to now execute step 1 — continues the same turn.
        nudge = (
            f"Plan committed for topic: {plan.topic!r}.\n"
            f"Steps: {[s.id for s in plan.steps]}.\n"
            f"Now execute step `{first.id}` ({first.phase}): {first.goal}\n"
            "When that step is complete, call `complete_step`. "
            "Do NOT execute later steps in this turn."
        )
        _log.info("plan_lesson: committed %d steps, starting on %s", len(steps), first.id)
        return nudge


class CompleteStepTool(_SessionAwareTool):
    """Mark the current lesson step as done and end the turn."""

    @property
    def name(self) -> str:
        return "complete_step"

    @property
    def description(self) -> str:
        return (
            "Call this at the end of each lesson step, once you have finished "
            "explaining / drawing / quizzing for that step. It records a short "
            "summary to the session and hands control back to the student so "
            "they can react or ask questions before the next step runs."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Id of the step you just completed (e.g. 's1').",
                },
                "output_summary": {
                    "type": "string",
                    "description": (
                        "1-3 sentences summarising what happened in this step — "
                        "what was defined / explained / drawn / quizzed, and "
                        "(if relevant) how the student did. Used to pick up "
                        "context on later turns."
                    ),
                },
            },
            "required": ["id"],
        }

    async def execute(self, **kwargs: Any) -> str:  # type: ignore[override]
        session = self._session()
        if session is None:
            return "Error: complete_step requires an active session."
        plan = load(session)
        if plan is None:
            return "Error: no lesson plan on this session. Call `plan_lesson` first."

        step_id = str(kwargs.get("id") or "").strip()
        summary = str(kwargs.get("output_summary") or "").strip()
        step = plan.find(step_id)
        if step is None:
            return f"Error: no such step `{step_id}`. Valid ids: {[s.id for s in plan.steps]}"

        nxt = complete(plan, step_id, summary)
        save(session, plan)

        if nxt is None:
            body = (
                f"Step `{step_id}` complete. Lesson finished. "
                "Wrap up in ONE short sentence to the student — do NOT start a new plan "
                "unless the student asks for a new topic."
            )
        else:
            body = (
                f"Step `{step_id}` recorded. Next queued: `{nxt.id}` ({nxt.phase}) — {nxt.goal}. "
                "**STOP now.** End your reply in ONE short sentence that invites the student's "
                "reaction (e.g. \"Does that part make sense so far?\"). Do NOT execute the next "
                "step in this turn — wait for the student's reply first."
            )
        _log.info("complete_step: %s done, next=%s", step_id, nxt.id if nxt else None)
        return body


__all__ = ["PlanLessonTool", "CompleteStepTool"]
