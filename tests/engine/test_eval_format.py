from __future__ import annotations

import pytest

from chess_trainer.engine.eval_format import BAR_MAX, BAR_MIN, MINUS, bar_fraction, format_eval
from chess_trainer.engine.eval_types import Eval


def test_positive_score_gets_a_plus():
    assert format_eval(Eval(cp=45)) == "+0.45"


def test_negative_score_gets_a_typographic_minus():
    assert format_eval(Eval(cp=-120)) == f"{MINUS}1.20"
    assert MINUS != "-"


def test_zero_is_unsigned():
    assert format_eval(Eval(cp=0)) == "0.00"


def test_two_decimal_places_always():
    assert format_eval(Eval(cp=100)) == "+1.00"
    assert format_eval(Eval(cp=7)) == "+0.07"


def test_large_scores_are_not_truncated():
    assert format_eval(Eval(cp=2550)) == "+25.50"


def test_white_mate_has_no_sign():
    assert format_eval(Eval(mate=3)) == "M3"


def test_black_mate_is_signed():
    assert format_eval(Eval(mate=-3)) == f"{MINUS}M3"


def test_mate_in_one():
    assert format_eval(Eval(mate=1)) == "M1"


def test_bar_fraction_is_a_half_at_equality():
    assert bar_fraction(Eval(cp=0)) == pytest.approx(0.5)


def test_bar_fraction_grows_with_white_advantage():
    assert bar_fraction(Eval(cp=300)) > bar_fraction(Eval(cp=0)) > bar_fraction(Eval(cp=-300))


def test_bar_fraction_is_clamped():
    assert bar_fraction(Eval(mate=1)) == pytest.approx(BAR_MAX)
    assert bar_fraction(Eval(mate=-1)) == pytest.approx(BAR_MIN)
    assert BAR_MIN <= bar_fraction(Eval(cp=-99999)) <= BAR_MAX
