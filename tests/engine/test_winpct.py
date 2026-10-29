from __future__ import annotations

import pytest

from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.winpct import (
    CP_CEILING,
    win_percent,
    win_percent_drop,
    win_percent_from_cp,
)


def test_equal_position_is_fifty_percent():
    assert win_percent_from_cp(0) == pytest.approx(50.0)


def test_curve_is_symmetric():
    assert win_percent_from_cp(300) == pytest.approx(100 - win_percent_from_cp(-300))


def test_curve_is_monotonic():
    values = [win_percent_from_cp(cp) for cp in range(-800, 801, 100)]
    assert values == sorted(values)


def test_matches_the_published_formula():
    # 50 + 50 * (2 / (1 + exp(-0.00368208 * 100)) - 1)
    assert win_percent_from_cp(100) == pytest.approx(59.1, abs=0.1)


def test_values_stay_within_bounds():
    assert 0 <= win_percent_from_cp(-100000) <= 100
    assert 0 <= win_percent_from_cp(100000) <= 100


def test_cp_is_capped_at_the_ceiling():
    assert win_percent_from_cp(CP_CEILING) == win_percent_from_cp(CP_CEILING * 10)


def test_win_percent_uses_the_movers_view():
    evaluation = Eval(cp=200)  # good for White
    assert win_percent(evaluation, white_to_move=True) > 50
    assert win_percent(evaluation, white_to_move=False) < 50


def test_mate_for_the_mover_is_one_hundred():
    assert win_percent(Eval(mate=3), white_to_move=True) == 100.0
    assert win_percent(Eval(mate=-3), white_to_move=False) == 100.0


def test_mate_against_the_mover_is_zero():
    assert win_percent(Eval(mate=-3), white_to_move=True) == 0.0
    assert win_percent(Eval(mate=3), white_to_move=False) == 0.0


def test_drop_is_zero_for_a_move_that_keeps_the_evaluation():
    assert win_percent_drop(Eval(cp=20), Eval(cp=20), mover_is_white=True) == 0.0


def test_drop_is_positive_when_white_worsens_the_position():
    drop = win_percent_drop(Eval(cp=0), Eval(cp=-300), mover_is_white=True)
    assert drop == pytest.approx(25.1, abs=0.2)


def test_drop_for_black_uses_blacks_perspective():
    # Black moves and the White-view score rises: bad for Black.
    drop = win_percent_drop(Eval(cp=0), Eval(cp=300), mover_is_white=False)
    assert drop == pytest.approx(25.1, abs=0.2)


def test_improving_moves_never_count_as_a_drop():
    assert win_percent_drop(Eval(cp=0), Eval(cp=500), mover_is_white=True) == 0.0


def test_walking_into_mate_is_a_full_drop():
    drop = win_percent_drop(Eval(cp=0), Eval(mate=-1), mover_is_white=True)
    assert drop == pytest.approx(50.0)


def test_missing_a_mate_registers_a_drop():
    drop = win_percent_drop(Eval(mate=2), Eval(cp=0), mover_is_white=True)
    assert drop == pytest.approx(50.0)
