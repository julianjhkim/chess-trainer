"""Turning what happened on a card into an SM-2 quality.

Grading is automatic: there are no self-assessment buttons, only what the
attempt log says.

======================  =======
outcome                 quality
======================  =======
right first time              4
right after a retry           3
answer revealed               1
======================  =======
"""

from __future__ import annotations

QUALITY_FIRST_TRY = 4
QUALITY_AFTER_RETRY = 3
QUALITY_SHOWN = 1


def quality_for(*, attempts: int, used_show_answer: bool) -> int:
    """The SM-2 quality for an answered card.

    ``attempts`` counts every move tried, so a first-try success is 1.
    Revealing the answer always grades as a failure, however few tries it took.
    """
    if used_show_answer:
        return QUALITY_SHOWN
    if attempts <= 1:
        return QUALITY_FIRST_TRY
    return QUALITY_AFTER_RETRY


def is_pass(quality: int) -> bool:
    from chess_trainer.srs.sm2 import PASS_QUALITY

    return quality >= PASS_QUALITY


def describe(quality: int) -> str:
    """A short explanation of a grade, for the UI."""
    return {
        QUALITY_FIRST_TRY: "right first time",
        QUALITY_AFTER_RETRY: "right after a retry",
        QUALITY_SHOWN: "answer revealed",
    }.get(quality, f"quality {quality}")
