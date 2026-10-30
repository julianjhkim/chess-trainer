from __future__ import annotations

import pytest

from chess_trainer.engine.classify import Classification
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.positions import walk
from chess_trainer.review.first_inaccuracy import assess, find_first

POSITIONS = walk(["e2e4", "e7e5", "g1f3", "b8c6"])
WHITE_MOVE = POSITIONS[0]
BLACK_MOVE = POSITIONS[1]


def test_a_quiet_move_is_good():
    result = assess(WHITE_MOVE, Eval(cp=20), Eval(cp=15))
    assert result.classification is Classification.GOOD
    assert result.win_percent_drop < 10


def test_a_white_blunder_is_measured_from_whites_view():
    result = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=-800))
    assert result.classification is Classification.BLUNDER
    assert result.win_percent_drop == pytest.approx(45.0, abs=0.5)


def test_a_black_blunder_is_measured_from_blacks_view():
    """The same White-view swing, but it is Black who moved, so Black loses out."""
    result = assess(BLACK_MOVE, Eval(cp=0), Eval(cp=800))
    assert result.classification is Classification.BLUNDER


def test_a_move_good_for_black_is_not_blacks_mistake():
    result = assess(BLACK_MOVE, Eval(cp=0), Eval(cp=-800))
    assert result.classification is Classification.GOOD
    assert result.win_percent_drop == 0


def test_win_percentages_are_recorded_from_the_movers_view():
    result = assess(WHITE_MOVE, Eval(cp=200), Eval(cp=0))
    assert result.win_percent_before > 50
    assert result.win_percent_after == pytest.approx(50)


def test_mistake_band():
    result = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=-300))
    assert result.classification is Classification.MISTAKE


def test_inaccuracy_band():
    # 0 -> -150cp is a 13.5 point drop; -110cp is 9.99, just under the threshold.
    result = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=-150))
    assert result.classification is Classification.INACCURACY


def test_just_under_the_inaccuracy_threshold_is_still_good():
    result = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=-110))
    assert result.win_percent_drop < 10
    assert result.classification is Classification.GOOD


def test_walking_into_mate_is_a_blunder():
    result = assess(WHITE_MOVE, Eval(cp=0), Eval(mate=-2))
    assert result.classification is Classification.BLUNDER
    assert result.win_percent_drop == pytest.approx(50.0)


def test_missing_a_mate_is_a_blunder():
    result = assess(WHITE_MOVE, Eval(mate=2), Eval(cp=0))
    assert result.classification is Classification.BLUNDER


def test_mate_to_mate_is_fine():
    result = assess(WHITE_MOVE, Eval(mate=3), Eval(mate=2))
    assert result.classification is Classification.GOOD


def test_the_position_is_carried_through():
    result = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=0))
    assert result.position is WHITE_MOVE
    assert result.eval_before == Eval(cp=0)


def test_is_inaccuracy_or_worse_flag():
    good = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=0))
    bad = assess(WHITE_MOVE, Eval(cp=0), Eval(cp=-300))
    assert not good.is_inaccuracy_or_worse
    assert bad.is_inaccuracy_or_worse


# -- find_first ---------------------------------------------------------
def test_find_first_returns_none_when_all_moves_are_good():
    assessments = [assess(WHITE_MOVE, Eval(cp=0), Eval(cp=0)) for _ in range(5)]
    assert find_first(assessments) is None


def test_find_first_returns_the_earliest_slip():
    assessments = [
        assess(POSITIONS[0], Eval(cp=0), Eval(cp=0)),
        assess(POSITIONS[2], Eval(cp=0), Eval(cp=-300)),
        assess(POSITIONS[2], Eval(cp=0), Eval(cp=-900)),
    ]
    found = find_first(assessments)
    assert found.position.ply == 2
    assert found.classification is Classification.MISTAKE


def test_find_first_of_nothing_is_none():
    assert find_first([]) is None


def test_find_first_stops_consuming_the_iterator():
    """It must not pull more assessments than it needs: the engine is behind them."""
    produced = []

    def generate():
        for drop_cp in (0, -300, -900):
            produced.append(drop_cp)
            yield assess(WHITE_MOVE, Eval(cp=0), Eval(cp=drop_cp))

    find_first(generate())
    assert produced == [0, -300]
