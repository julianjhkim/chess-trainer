"""Building and running one game review.

Two halves:

* :func:`build_review` -- the I/O part. It walks my moves in game order and
  analyses each one, **stopping at the first inaccuracy**. Since the review ends
  there anyway, a slip on move 8 costs a handful of engine calls rather than one
  per ply of the whole game. Everything is cached by ``(fen, depth)``, so a
  second review of the same game is instant.

* :class:`ReviewSession` -- the interactive part. It tracks attempts and whether
  the answer was revealed, decides when the review is over, and can hand the
  result to the history table.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from chess_trainer import rules
from chess_trainer.db.game_reviews_repo import GameReview
from chess_trainer.engine import analysis
from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.stockfish import Analyser
from chess_trainer.pgn import positions as positions_module
from chess_trainer.pgn.parse import ParsedGame
from chess_trainer.review import first_inaccuracy, my_moves, verdict
from chess_trainer.review.first_inaccuracy import MoveAssessment
from chess_trainer.review.verdict import ReviewSummary


@dataclass(frozen=True, slots=True)
class ReviewTarget:
    """The position the review stops at, and the answer to it."""

    ply: int
    move_number: int
    move_label: str
    fen_before: str
    #: The moves leading to ``fen_before``, for the animated auto-replay.
    replay_ucis: list[str]
    my_move_uci: str
    my_move_san: str
    classification: str
    eval_before: Eval
    eval_after: Eval
    win_percent_drop: float
    best_move_uci: str
    best_move_san: str
    mover_is_white: bool


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    """The outcome of analysing a game: a target to solve, or nothing to fix."""

    game_id: str
    my_colour: str
    depth: int
    my_move_count: int
    moves_assessed: int
    target: ReviewTarget | None = None

    @property
    def has_target(self) -> bool:
        return self.target is not None


def count_my_moves(parsed: ParsedGame, my_colour: str) -> int:
    """How many moves are mine, without analysing anything.

    Lets the UI show "move 4 of 21" progress before the engine has started.
    """
    return len(my_moves.mine(positions_module.from_parsed(parsed), my_colour))


def build_review(
    conn: sqlite3.Connection,
    engine: Analyser,
    parsed: ParsedGame,
    *,
    game_id: str,
    my_colour: str,
    depth: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> ReviewPlan:
    """Analyse my moves until the first inaccuracy, and build the plan.

    ``on_progress(assessed, total)`` is called after each of my moves. A long
    game can take a minute or more at depth 20, so the caller needs some way to
    show that something is happening.
    """
    all_positions = positions_module.from_parsed(parsed)
    mine = my_moves.mine(all_positions, my_colour)

    assessed = 0
    for position in mine:
        before = analysis.analyse(conn, engine, position.fen_before, depth)
        after = analysis.analyse(conn, engine, position.fen_after, depth)
        assessment = first_inaccuracy.assess(
            position, before.evaluation, after.evaluation
        )
        assessed += 1
        if on_progress is not None:
            on_progress(assessed, len(mine))

        if not assessment.is_inaccuracy_or_worse:
            continue

        # `before.best_move` is the engine's top-1 at this very position and
        # depth, so the accepted answer comes free with the evaluation.
        #
        # Note it is possible, though rare, for the played move to *be* the
        # top-1 and still register a drop: the "after" evaluation searches one
        # ply deeper than the "before" one. Then the answer is simply the move
        # that was played, which solves on the first try.
        best_uci = before.best_move
        if best_uci is None:  # pragma: no cover - a move was played from here
            continue

        return ReviewPlan(
            game_id=game_id,
            my_colour=my_colour,
            depth=depth,
            my_move_count=len(mine),
            moves_assessed=assessed,
            target=_build_target(assessment, best_uci, all_positions),
        )

    return ReviewPlan(
        game_id=game_id,
        my_colour=my_colour,
        depth=depth,
        my_move_count=len(mine),
        moves_assessed=assessed,
        target=None,
    )


def _build_target(
    assessment: MoveAssessment,
    best_uci: str,
    all_positions: list[positions_module.PositionMove],
) -> ReviewTarget:
    position = assessment.position
    return ReviewTarget(
        ply=position.ply,
        move_number=position.move_number,
        move_label=position.move_label,
        fen_before=position.fen_before,
        replay_ucis=positions_module.line_up_to(all_positions, position.ply),
        my_move_uci=position.uci,
        my_move_san=position.san,
        classification=assessment.classification.value,
        eval_before=assessment.eval_before,
        eval_after=assessment.eval_after,
        win_percent_drop=assessment.win_percent_drop,
        best_move_uci=best_uci,
        best_move_san=rules.san_of(position.fen_before, best_uci),
        mover_is_white=position.mover_is_white,
    )


@dataclass(slots=True)
class ReviewSession:
    """Live state for one review: attempts, reveals, and when it ends."""

    plan: ReviewPlan
    attempts: list[str] = field(default_factory=list)
    used_show_answer: bool = False
    used_hint: bool = False
    solved: bool = False
    recorded: bool = False

    @property
    def target(self) -> ReviewTarget | None:
        return self.plan.target

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def finished(self) -> bool:
        """A review ends when the move is found, revealed, or never needed."""
        return self.solved or self.used_show_answer or not self.plan.has_target

    def attempt(self, uci: str) -> bool:
        """Record an attempt and say whether it was the engine's top move.

        Retries are unlimited, so a wrong answer simply adds to the count.
        """
        if self.target is None:
            raise ValueError("This review has no position to solve.")
        self.attempts.append(uci)
        if verdict.is_correct(uci, self.target.best_move_uci):
            self.solved = True
        return self.solved

    def hint(self) -> str:
        """The square of the piece the answer moves. Only while still solving."""
        if self.target is None:
            raise ValueError("This review has no position to solve.")
        if self.finished:
            raise ValueError("This review is already finished.")
        self.used_hint = True
        return self.target.best_move_uci[:2]

    def show_answer(self) -> str:
        """Reveal the answer, which ends the review."""
        if self.target is None:
            raise ValueError("This review has no position to solve.")
        self.used_show_answer = True
        return self.target.best_move_uci

    def summary(self) -> ReviewSummary:
        """The short report for the end of the review."""
        target = self.target
        if target is None:
            return verdict.no_inaccuracy_summary(attempts=self.attempt_count)
        return ReviewSummary(
            move_label=target.move_label,
            my_move_san=target.my_move_san,
            my_move_uci=target.my_move_uci,
            classification=target.classification,
            best_move_san=target.best_move_san,
            best_move_uci=target.best_move_uci,
            eval_before=target.eval_before,
            eval_after=target.eval_after,
            win_percent_drop=target.win_percent_drop,
            attempts=self.attempt_count,
            used_show_answer=self.used_show_answer,
            found_an_inaccuracy=True,
            used_hint=self.used_hint,
        )

    def to_history(self, reviewed_on: date) -> GameReview:
        """This review as a row for the history table."""
        target = self.target
        if target is None:
            return GameReview(
                game_id=self.plan.game_id,
                depth=self.plan.depth,
                reviewed_on=reviewed_on,
                attempts=self.attempt_count,
                used_show_answer=False,
            )
        return GameReview(
            game_id=self.plan.game_id,
            depth=self.plan.depth,
            reviewed_on=reviewed_on,
            first_inaccuracy_ply=target.ply,
            my_move_uci=target.my_move_uci,
            my_move_san=target.my_move_san,
            classification=target.classification,
            best_move_uci=target.best_move_uci,
            best_move_san=target.best_move_san,
            eval_before=target.eval_before,
            eval_after=target.eval_after,
            win_percent_drop=target.win_percent_drop,
            attempts=self.attempt_count,
            used_show_answer=self.used_show_answer,
            used_hint=self.used_hint,
        )
