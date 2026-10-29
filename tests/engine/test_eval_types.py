from __future__ import annotations

import pytest

from chess_trainer.engine.eval_types import Eval


def test_centipawn_constructor():
    assert Eval.centipawns(50) == Eval(cp=50)


def test_mate_constructor():
    assert Eval.mate_in(-2) == Eval(mate=-2)


def test_exactly_one_score_is_required():
    with pytest.raises(ValueError, match="exactly one"):
        Eval()
    with pytest.raises(ValueError, match="exactly one"):
        Eval(cp=10, mate=2)


def test_mate_zero_is_rejected():
    with pytest.raises(ValueError, match="mate=0"):
        Eval(mate=0)


def test_cp_zero_is_allowed():
    assert Eval(cp=0).cp == 0


def test_is_mate_flag():
    assert Eval(mate=3).is_mate
    assert not Eval(cp=300).is_mate


def test_pov_white_is_identity():
    evaluation = Eval(cp=45)
    assert evaluation.pov(True) is evaluation


def test_pov_black_negates_centipawns():
    assert Eval(cp=45).pov(False) == Eval(cp=-45)


def test_pov_black_negates_mate():
    assert Eval(mate=3).pov(False) == Eval(mate=-3)


def test_flip_is_pov_black():
    assert Eval(cp=120).flip() == Eval(cp=-120)


def test_double_flip_returns_the_original():
    evaluation = Eval(cp=-77)
    assert evaluation.flip().flip() == evaluation


def test_from_pov_keeps_white_scores_as_is():
    assert Eval.from_pov(cp=30, mate=None, white_to_move=True) == Eval(cp=30)


def test_from_pov_flips_black_scores():
    assert Eval.from_pov(cp=30, mate=None, white_to_move=False) == Eval(cp=-30)
    assert Eval.from_pov(cp=None, mate=2, white_to_move=False) == Eval(mate=-2)


def test_mate_favours_white_reports_the_side():
    assert Eval(mate=4).mate_favours_white is True
    assert Eval(mate=-4).mate_favours_white is False
    assert Eval(cp=0).mate_favours_white is None


def test_eval_is_hashable_and_comparable():
    assert Eval(cp=10) == Eval(cp=10)
    assert len({Eval(cp=10), Eval(cp=10), Eval(cp=20)}) == 2
