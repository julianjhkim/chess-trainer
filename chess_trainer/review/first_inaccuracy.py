"""Classifying my moves and finding the first one that went wrong.

Pure: it works on evaluations that someone else has already obtained, so the
thresholds and the search for the first slip are testable with no engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chess_trainer.engine.classify import Classification, classify
from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.winpct import win_percent, win_percent_drop
from chess_trainer.pgn.positions import PositionMove


@dataclass(frozen=True, slots=True)
class MoveAssessment:
    """What one of my moves cost, and what that makes it."""

    position: PositionMove
    eval_before: Eval
    eval_after: Eval
    win_percent_before: float
    win_percent_after: float
    win_percent_drop: float
    classification: Classification

    @property
    def is_inaccuracy_or_worse(self) -> bool:
        return self.classification.is_inaccuracy_or_worse


def assess(
    position: PositionMove, eval_before: Eval, eval_after: Eval
) -> MoveAssessment:
    """Classify one move from the evaluations either side of it.

    Both evaluations are White's-view; the win percentages are taken from the
    mover's perspective, which is what the Lichess model expects.
    """
    mover_is_white = position.mover_is_white
    before = win_percent(eval_before, white_to_move=mover_is_white)
    after = win_percent(eval_after, white_to_move=mover_is_white)
    drop = win_percent_drop(eval_before, eval_after, mover_is_white=mover_is_white)
    return MoveAssessment(
        position=position,
        eval_before=eval_before,
        eval_after=eval_after,
        win_percent_before=before,
        win_percent_after=after,
        win_percent_drop=drop,
        classification=classify(drop),
    )


def find_first(assessments: Iterable[MoveAssessment]) -> MoveAssessment | None:
    """The first assessment that is an inaccuracy or worse, if any.

    Takes an iterable so a generator can stop the engine as soon as one is
    found rather than analysing the rest of the game.
    """
    for assessment in assessments:
        if assessment.is_inaccuracy_or_worse:
            return assessment
    return None
