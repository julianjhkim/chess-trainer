from __future__ import annotations

from chess_trainer.engine.eval_types import Eval
from chess_trainer.review.verdict import (
    ReviewSummary,
    is_correct,
    no_inaccuracy_summary,
)


def test_matching_the_engine_move_is_correct():
    assert is_correct("e2e4", "e2e4")


def test_a_different_move_is_wrong():
    assert not is_correct("d2d4", "e2e4")


def test_nothing_matches_a_missing_best_move():
    assert not is_correct("e2e4", None)


def test_promotion_pieces_must_match():
    assert is_correct("a7a8q", "a7a8q")
    assert not is_correct("a7a8n", "a7a8q")


def test_no_inaccuracy_summary_is_empty_but_well_formed():
    summary = no_inaccuracy_summary()
    assert not summary.found_an_inaccuracy
    assert summary.my_move_san is None
    assert summary.best_move_san is None
    assert summary.attempts == 0
    assert not summary.used_show_answer


def test_no_inaccuracy_summary_can_carry_attempts():
    assert no_inaccuracy_summary(attempts=2).attempts == 2


def summary(**overrides) -> ReviewSummary:
    base = dict(
        move_label="11.f4",
        my_move_san="f4",
        my_move_uci="f2f4",
        classification="blunder",
        best_move_san="O-O-O",
        best_move_uci="e1c1",
        eval_before=Eval(cp=698),
        eval_after=Eval(cp=-684),
        win_percent_drop=85.4,
        attempts=1,
        used_show_answer=False,
        found_an_inaccuracy=True,
    )
    base.update(overrides)
    return ReviewSummary(**base)


def test_solved_first_try():
    assert summary(attempts=1).solved_first_try


def test_not_first_try_after_retries():
    assert not summary(attempts=3).solved_first_try


def test_revealing_the_answer_is_not_a_first_try_solve():
    assert not summary(attempts=1, used_show_answer=True).solved_first_try


def test_zero_attempts_is_not_a_first_try_solve():
    assert not summary(attempts=0).solved_first_try
