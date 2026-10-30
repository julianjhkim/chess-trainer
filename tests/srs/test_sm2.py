"""The modified SM-2 maths."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from chess_trainer.srs import sm2
from chess_trainer.srs.sm2 import SchedulingState

TODAY = date(2026, 10, 30)


def test_the_starting_state():
    state = sm2.new_state()
    assert state.n == 0
    assert state.ef == 2.5
    assert state.interval_days == 0
    assert state.is_new


def test_the_spec_constants():
    assert sm2.INITIAL_EF == 2.5
    assert sm2.MIN_EF == 1.3
    assert sm2.PASS_QUALITY == 3
    assert sm2.FIRST_INTERVAL == 1
    assert sm2.SECOND_INTERVAL == 6
    assert sm2.LAPSE_MULTIPLIER == 0.5


# -- ease factor ---------------------------------------------------------
def test_a_perfect_recall_leaves_the_ease_alone():
    """ef + 0.1 - 1*(0.08 + 1*0.02) == ef"""
    assert sm2.next_ef(2.5, 4) == pytest.approx(2.5)


def test_a_retry_lowers_the_ease_a_little():
    assert sm2.next_ef(2.5, 3) == pytest.approx(2.36)


def test_a_revealed_answer_lowers_the_ease_a_lot():
    assert sm2.next_ef(2.5, 1) == pytest.approx(1.96)


def test_quality_five_raises_the_ease():
    assert sm2.next_ef(2.5, 5) == pytest.approx(2.6)


def test_the_ease_has_a_floor():
    assert sm2.next_ef(1.3, 0) == 1.3
    assert sm2.next_ef(1.4, 1) == 1.3
    assert sm2.next_ef(1.35, 1) == 1.3


def test_the_ease_floor_holds_over_many_failures():
    ef = 2.5
    for _ in range(20):
        ef = sm2.next_ef(ef, 1)
    assert ef == 1.3


# -- intervals on success ------------------------------------------------
def test_the_first_pass_is_one_day():
    result = sm2.review(sm2.new_state(), 4, today=TODAY)
    assert result.interval_days == 1
    assert result.due_on == TODAY + timedelta(days=1)
    assert result.state.n == 1


def test_the_second_pass_is_six_days():
    result = sm2.review(SchedulingState(n=1, ef=2.5, interval_days=1), 4, today=TODAY)
    assert result.interval_days == 6
    assert result.state.n == 2


def test_later_passes_multiply_by_the_ease():
    result = sm2.review(SchedulingState(n=2, ef=2.5, interval_days=6), 4, today=TODAY)
    assert result.interval_days == 15  # round(6 * 2.5)
    assert result.state.n == 3


def test_the_interval_uses_the_ease_before_this_answer():
    """Textbook SM-2, and the order the rules are written in."""
    result = sm2.review(SchedulingState(n=2, ef=2.0, interval_days=10), 3, today=TODAY)
    assert result.interval_days == 20  # 10 * 2.0, not 10 * 1.86
    assert result.state.ef == pytest.approx(1.86)


def test_the_ladder_over_several_passes():
    state = sm2.new_state()
    intervals = []
    for _ in range(5):
        result = sm2.review(state, 4, today=TODAY)
        intervals.append(result.interval_days)
        state = result.state
    assert intervals == [1, 6, 15, 38, 95]


def test_rounding_is_pythons_round_to_even():
    """round(15 * 2.5) == round(37.5) == 38, not 37: banker's rounding."""
    result = sm2.review(SchedulingState(n=3, ef=2.5, interval_days=15), 4, today=TODAY)
    assert result.interval_days == 38


def test_a_retry_pass_still_advances():
    result = sm2.review(SchedulingState(n=2, ef=2.5, interval_days=6), 3, today=TODAY)
    assert result.passed
    assert result.interval_days == 15
    assert result.state.n == 3
    assert result.state.ef == pytest.approx(2.36)


# -- intervals on failure ------------------------------------------------
def test_a_failure_halves_rather_than_resetting():
    """The spec's departure from textbook SM-2."""
    result = sm2.review(SchedulingState(n=4, ef=2.5, interval_days=38), 1, today=TODAY)
    assert result.interval_days == 19
    assert not result.passed
    assert result.previous_interval_days == 38


def test_a_failure_leaves_the_ladder_position_alone():
    """n survives a lapse, which is what makes halving the interval mean something."""
    result = sm2.review(SchedulingState(n=4, ef=2.5, interval_days=38), 1, today=TODAY)
    assert result.state.n == 4


def test_a_failure_never_goes_below_one_day():
    for interval in (0, 1, 2):
        result = sm2.review(
            SchedulingState(n=1, ef=2.5, interval_days=interval), 1, today=TODAY
        )
        assert result.interval_days == 1


def test_a_failed_new_card_is_due_tomorrow():
    result = sm2.review(sm2.new_state(), 1, today=TODAY)
    assert result.interval_days == 1
    assert result.due_on == TODAY + timedelta(days=1)


def test_a_long_interval_is_halved_not_destroyed():
    result = sm2.review(SchedulingState(n=9, ef=2.5, interval_days=365), 1, today=TODAY)
    assert result.interval_days == 182


def test_recovering_after_a_failure_continues_from_the_halved_interval():
    """The next pass grows from the halved interval, not from one day."""
    failed = sm2.review(SchedulingState(n=4, ef=2.5, interval_days=38), 1, today=TODAY)
    assert failed.interval_days == 19

    recovered = sm2.review(failed.state, 4, today=TODAY)
    # 19 * 1.96 (the ease after the lapse), not back to 1.
    assert recovered.interval_days == 37
    assert recovered.state.n == 5


def test_a_lapse_costs_one_step_not_the_whole_history():
    """A long-known card recovers near where it was, not at the beginning."""
    state = SchedulingState(n=9, ef=2.5, interval_days=365)
    failed = sm2.review(state, 1, today=TODAY)
    recovered = sm2.review(failed.state, 4, today=TODAY)
    assert failed.interval_days == 182
    assert recovered.interval_days == 357  # round(182 * 1.96)
    assert recovered.interval_days > 100


def test_a_card_that_never_passed_stays_at_one_day():
    """The n == 0 exception, which the pass rule already gives us."""
    failed = sm2.review(sm2.new_state(), 1, today=TODAY)
    assert failed.state.n == 0
    assert failed.interval_days == 1

    recovered = sm2.review(failed.state, 4, today=TODAY)
    assert recovered.interval_days == 1
    assert recovered.state.n == 1


def test_repeated_lapses_keep_halving_without_restarting():
    # round(12.5) is 12, not 13: Python rounds halves to even.
    state = SchedulingState(n=5, ef=2.5, interval_days=100)
    for expected in (50, 25, 12, 6, 3):
        result = sm2.review(state, 1, today=TODAY)
        assert result.interval_days == expected
        assert result.state.n == 5
        state = result.state


def test_halving_bottoms_out_at_one_day():
    state = SchedulingState(n=5, ef=2.5, interval_days=2)
    for _ in range(4):
        state = sm2.review(state, 1, today=TODAY).state
        assert state.interval_days >= 1
    assert state.interval_days == 1


def test_n_counts_passes_rather_than_consecutive_passes():
    state = sm2.new_state()
    for quality in (4, 4, 1, 4):
        state = sm2.review(state, quality, today=TODAY).state
    assert state.n == 3  # three passes; the lapse did not reset it


# -- validation ----------------------------------------------------------
def test_a_quality_out_of_range_is_rejected():
    with pytest.raises(ValueError, match="between 0 and 5"):
        sm2.review(sm2.new_state(), 6, today=TODAY)
    with pytest.raises(ValueError, match="between 0 and 5"):
        sm2.review(sm2.new_state(), -1, today=TODAY)


def test_quality_zero_is_allowed():
    assert not sm2.review(sm2.new_state(), 0, today=TODAY).passed


def test_the_due_date_follows_the_interval():
    result = sm2.review(SchedulingState(n=2, ef=2.5, interval_days=6), 4, today=TODAY)
    assert (result.due_on - TODAY).days == result.interval_days


def test_next_interval_is_usable_on_its_own():
    assert sm2.next_interval(sm2.new_state(), 4) == 1
    assert sm2.next_interval(SchedulingState(n=1, ef=2.5, interval_days=1), 4) == 6
