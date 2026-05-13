"""Lesson plan state for structured teaching.

A `LessonPlan` is a short, ordered sequence of `LessonStep`s the tutor
commits to at the start of a teaching turn. Subsequent user turns advance
through the plan one step at a time: the LLM sees `current_step_id` and is
told to execute *only* that step before handing control back to the student.

The plan is persisted on the session as `metadata["lesson_plan"]`, so it
survives page reloads and uvicorn restarts automatically (the session JSONL
already saves metadata).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


LessonPhase = Literal["assess", "define", "explain", "check", "adapt", "wrap_up"]
"""Pedagogical phases. The five core phases are assess/define/explain/check/adapt;
`wrap_up` is a convenience for a final summary or next-step pointer."""


class LessonStep(BaseModel):
    """One step of a lesson plan."""

    id: str = Field(description="Short stable id, e.g. 's1', 's2-check'.")
    phase: LessonPhase = Field(
        description="Which teaching phase this step belongs to."
    )
    goal: str = Field(
        description=(
            "One short sentence in the student's language describing what this "
            "step achieves. The LLM will see this verbatim when executing the step."
        ),
    )
    requires: list[str] = Field(
        default_factory=list,
        description="Ids of steps that must complete before this one starts.",
    )
    tools_hint: list[str] = Field(
        default_factory=list,
        description=(
            "Advisory list of tools the step may call (e.g. ['visualize']). "
            "The LLM still decides; this just primes expectations."
        ),
    )
    status: Literal["pending", "in_progress", "done", "skipped"] = "pending"
    output_summary: str = Field(
        default="",
        description="Filled in when `complete_step` runs. 1-3 sentences.",
    )


class LessonPlan(BaseModel):
    """A committed teaching plan for a topic."""

    topic: str = Field(description="What the student wants to learn about.")
    steps: list[LessonStep] = Field(min_length=1, max_length=8)
    current_step_id: str | None = Field(
        default=None,
        description="The step the LLM should execute on the next turn.",
    )

    def find(self, step_id: str) -> LessonStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def pending_after(self, step_id: str) -> LessonStep | None:
        """Return the next pending step after the given one (or the first pending step)."""
        seen_current = step_id is None
        for s in self.steps:
            if seen_current and s.status == "pending":
                if all(self.find(r) and self.find(r).status == "done" for r in s.requires):
                    return s
            if s.id == step_id:
                seen_current = True
        return None

    def first_pending(self) -> LessonStep | None:
        for s in self.steps:
            if s.status == "pending":
                return s
        return None

    def is_complete(self) -> bool:
        return all(s.status in ("done", "skipped") for s in self.steps)


__all__ = ["LessonPhase", "LessonStep", "LessonPlan"]
