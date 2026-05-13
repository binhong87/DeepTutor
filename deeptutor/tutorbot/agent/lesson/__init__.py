"""Structured lesson planning state for the TutorBot agent.

A `LessonPlan` is a short, ordered list of `LessonStep`s that the agent
commits to up-front for any substantive teaching request, then works
through one step per user turn.
"""

from .plan import LessonPhase, LessonPlan, LessonStep
from .store import advance_to, clear, complete, load, render_status_block, save

__all__ = [
    "LessonPhase",
    "LessonStep",
    "LessonPlan",
    "load",
    "save",
    "clear",
    "advance_to",
    "complete",
    "render_status_block",
]
