"""Session-metadata-backed store for `LessonPlan`.

The plan lives on `Session.metadata["lesson_plan"]` as a plain dict (so it
survives the existing JSONL serialisation untouched). This module just
encapsulates the (de)serialisation and a few convenience advance helpers.
"""

from __future__ import annotations

import re
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


def insert_after(plan: LessonPlan, anchor_id: str, new_step: LessonStep) -> bool:
    """Insert `new_step` immediately after `anchor_id` in the step list.

    Used by the `insert_step` tool when the tutor needs to dynamically add an
    `adapt` step after a wrong check answer (or any step at runtime). Returns
    True on success, False if `anchor_id` doesn't exist or the new id is
    already taken.
    """
    if plan.find(new_step.id) is not None:
        return False
    for i, s in enumerate(plan.steps):
        if s.id == anchor_id:
            plan.steps.insert(i + 1, new_step)
            return True
    return False


def render_status_block(plan: LessonPlan, lang: str = "en") -> str:
    """Human-readable one-block summary of the plan for injection into prompts.

    `lang` selects the wording so the bot doesn't get pushed into English by
    English scaffolding when the student is writing in Chinese.
    """
    if lang == "zh":
        lines = [f"# 当前课程：{plan.topic}"]
    else:
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
        if lang == "zh":
            lines.append(
                f"\n**你正在执行步骤 `{plan.current_step_id}`。只执行该步骤，然后调用 `complete_step`。**"
            )
        else:
            lines.append(
                f"\n**You are on step `{plan.current_step_id}`. Execute only that step, then call `complete_step`.**"
            )
    elif plan.is_complete():
        if lang == "zh":
            lines.append(
                "\n**课程已完成。** 如果学生提出后续问题，直接回答即可——除非他们请求一个新主题，否则不需要再制定新计划。"
            )
        else:
            lines.append(
                "\n**Lesson complete.** If the student asks a follow-up, answer directly — no need for a new plan unless they request a new topic."
            )
    return "\n".join(lines)


# Match any CJK ideograph (Han) or CJK punctuation. Hits Chinese, Japanese
# kanji, and traditional Chinese alike. Hangul/Kana are excluded — they have
# their own ranges and the rest of the system doesn't localize for them yet.
_CJK_RE = re.compile(r"[一-鿿㐀-䶿＀-￯　-〿]")


def detect_message_lang(message: str) -> str:
    """Return "zh" if the message contains CJK characters, else "en".

    Used to localize the runtime guidance nudges that wrap the student's
    message before it reaches the LLM. The check is conservative: a single
    CJK character is enough, because mixed Chinese-English student prompts
    should still get the Chinese scaffolding so the model continues in
    Chinese.
    """
    if not message:
        return "en"
    return "zh" if _CJK_RE.search(message) else "en"


# ── Heuristics ────────────────────────────────────────────────────────────────

# Verbs / phrases that strongly indicate a pedagogical request. Checked
# case-insensitively against the user message. Over-triggering is acceptable
# (a 1-step plan is still useful structure); under-triggering loses the whole
# point of the mechanism.
_TEACHING_KEYWORDS = (
    # Chinese
    "讲解", "讲讲", "讲一讲", "解释", "介绍", "说明", "阐述",
    "什么是", "怎么理解", "怎么", "如何",
    "系统地讲", "图文", "画一下", "画出", "帮我画",
    # English
    "explain", "walk me through", "walk through", "show me how",
    "teach me", "tutorial", "lesson on", "lesson about",
    "help me understand", "help me learn", "introduction to",
    "what is the", "how does", "how do",
)


def looks_like_teaching_request(message: str) -> bool:
    """Return True if `message` reads like a multi-part teaching request.

    Used to decide whether to inject a runtime nudge asking the LLM to call
    `plan_lesson` before doing anything else. False positives are cheap
    (the LLM will make a 1-2 step plan); false negatives skip the structure
    entirely, which is the worse failure.
    """
    if not message:
        return False
    lower = message.lower()
    return any(kw in lower for kw in _TEACHING_KEYWORDS)


__all__ = [
    "load",
    "save",
    "clear",
    "advance_to",
    "complete",
    "insert_after",
    "render_status_block",
    "looks_like_teaching_request",
    "detect_message_lang",
]
