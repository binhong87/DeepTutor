"""Session-metadata-backed store for `LessonPlan`.

The plan lives on `Session.metadata["lesson_plan"]` as a plain dict (so it
survives the existing JSONL serialisation untouched). This module just
encapsulates the (de)serialisation and a few convenience advance helpers.
"""

from __future__ import annotations

from typing import Any

from deeptutor.tutorbot.session.manager import Session

from .plan import LessonPlan, LessonStep

_METADATA_KEY = "lesson_plan"


def load(session: Session) -> LessonPlan | None:
    """Read the session's current lesson plan, if any."""
    raw = session.metadata.get(_METADATA_KEY)
    if not raw:
        return None
    try:
        return LessonPlan.model_validate(raw)
    except Exception:
        # Defensive: if the metadata is corrupt, drop it rather than crashing.
        session.metadata.pop(_METADATA_KEY, None)
        return None


def save(session: Session, plan: LessonPlan) -> None:
    """Write the plan to session metadata (caller must still `session_mgr.save()`)."""
    session.metadata[_METADATA_KEY] = plan.model_dump(exclude_none=True)


def clear(session: Session) -> None:
    """Drop the plan entirely."""
    session.metadata.pop(_METADATA_KEY, None)


def advance_to(plan: LessonPlan, step_id: str) -> None:
    """Mark step `step_id` as the current step and set it in_progress."""
    step = plan.find(step_id)
    if step is None:
        return
    if step.status == "pending":
        step.status = "in_progress"
    plan.current_step_id = step_id


def complete(plan: LessonPlan, step_id: str, output_summary: str = "") -> LessonStep | None:
    """Mark `step_id` as done, set the next pending step as current, and return it."""
    step = plan.find(step_id)
    if step is None:
        return None
    step.status = "done"
    step.output_summary = output_summary.strip()[:400]  # bound the size
    # Find the next pending step whose requirements are all satisfied.
    nxt = plan.pending_after(step_id) or plan.first_pending()
    if nxt is not None:
        nxt.status = "in_progress"
        plan.current_step_id = nxt.id
    else:
        plan.current_step_id = None
    return nxt


def render_status_block(plan: LessonPlan) -> str:
    """Human-readable one-block summary of the plan for injection into prompts."""
    lines = [f"# Current lesson: {plan.topic}"]
    for s in plan.steps:
        marker = {
            "done": "[x]",
            "in_progress": "[>]",
            "skipped": "[-]",
            "pending": "[ ]",
        }.get(s.status, "[?]")
        lines.append(f"{marker} {s.id} ({s.phase}): {s.goal}")
        if s.output_summary and s.status == "done":
            lines.append(f"      ↳ {s.output_summary}")
    if plan.current_step_id:
        lines.append(f"\n**You are on step `{plan.current_step_id}`. Execute only that step, then call `complete_step`.**")
    elif plan.is_complete():
        lines.append("\n**Lesson complete.** If the student asks a follow-up, answer directly — no need for a new plan unless they request a new topic.")
    return "\n".join(lines)


__all__ = ["load", "save", "clear", "advance_to", "complete", "render_status_block"]
