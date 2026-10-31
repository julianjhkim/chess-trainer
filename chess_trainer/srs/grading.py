"""Turning what happened on a card into an SM-2 quality.

Grading is automatic: there are no self-assessment buttons, only what the
attempt log says.

=========================  =======  ======
outcome                    quality  result
=========================  =======  ======
right on the 1st try             4  pass
right on the 2nd try             3  pass
right on the 3rd or later        2  fail
answer revealed                  1  fail
=========================  =======  ======

One wrong try is a stumble; two or more mean the card was not really known, so
it fails like a reveal (the interval is halved and the card comes back later
in the session), only with a gentler hit to its ease.
"""

from __future__ import annotations

QUALITY_FIRST_TRY = 4
QUALITY_SECOND_TRY = 3
QUALITY_AFTER_RETRIES = 2
QUALITY_SHOWN = 1

#: From this many attempts on, a correct answer no longer passes.
FAILING_ATTEMPTS = 3


def quality_for(*, attempts: int, used_show_answer: bool) -> int:
    """The SM-2 quality for an answered card.

    ``attempts`` counts every move tried, so a first-try success is 1.
    Revealing the answer always grades as a failure, however few tries it took.
    """
    if used_show_answer:
        return QUALITY_SHOWN
    if attempts <= 1:
        return QUALITY_FIRST_TRY
    if attempts < FAILING_ATTEMPTS:
        return QUALITY_SECOND_TRY
    return QUALITY_AFTER_RETRIES


def is_pass(quality: int) -> bool:
    from chess_trainer.srs.sm2 import PASS_QUALITY

    return quality >= PASS_QUALITY


def describe(quality: int, attempts: int | None = None) -> str:
    """A short explanation of a grade, for the UI.

    With ``attempts``, a fail after retries says how many tries went wrong.
    """
    if quality == QUALITY_AFTER_RETRIES and attempts is not None and attempts > 1:
        wrong = attempts - 1
        return f"right after {wrong} wrong tries"
    return {
        QUALITY_FIRST_TRY: "right first time",
        QUALITY_SECOND_TRY: "right on the 2nd try",
        QUALITY_AFTER_RETRIES: "right after 2 or more wrong tries",
        QUALITY_SHOWN: "answer revealed",
    }.get(quality, f"quality {quality}")
