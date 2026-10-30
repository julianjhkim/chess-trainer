"""Judging an attempt and describing the outcome.

Pure. The engine's top-1 move at the analysis depth is the only accepted
answer, and the comparison happens here (server-side) rather than in the
browser.
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_trainer.engine.eval_types import Eval


def is_correct(attempt_uci: str, best_move_uci: str | None) -> bool:
    """Whether an attempt matches the engine's top choice."""
    if best_move_uci is None:
        return False
    return attempt_uci == best_move_uci


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    """The short report shown once the review ends."""

    #: None when the game held no inaccuracy at all.
    move_label: str | None
    my_move_san: str | None
    my_move_uci: str | None
    classification: str | None
    best_move_san: str | None
    best_move_uci: str | None
    eval_before: Eval | None
    eval_after: Eval | None
    win_percent_drop: float | None
    attempts: int
    used_show_answer: bool
    found_an_inaccuracy: bool

    @property
    def solved_first_try(self) -> bool:
        return self.attempts == 1 and not self.used_show_answer


def no_inaccuracy_summary(*, attempts: int = 0) -> ReviewSummary:
    """The summary for a game in which none of my moves lost enough to count."""
    return ReviewSummary(
        move_label=None,
        my_move_san=None,
        my_move_uci=None,
        classification=None,
        best_move_san=None,
        best_move_uci=None,
        eval_before=None,
        eval_after=None,
        win_percent_drop=None,
        attempts=attempts,
        used_show_answer=False,
        found_an_inaccuracy=False,
    )
