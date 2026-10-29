from __future__ import annotations

from datetime import date

from chess_trainer.streak.streak import compute, current_run, longest_run

D = date


def test_no_days_means_no_streak():
    result = compute([], today=D(2026, 10, 29))
    assert (result.current, result.longest, result.total_days) == (0, 0, 0)
    assert not result.active_today


def test_single_day_today():
    result = compute([D(2026, 10, 29)], today=D(2026, 10, 29))
    assert (result.current, result.longest) == (1, 1)
    assert result.active_today


def test_consecutive_days_count_up():
    days = [D(2026, 10, 27), D(2026, 10, 28), D(2026, 10, 29)]
    assert compute(days, today=D(2026, 10, 29)).current == 3


def test_streak_survives_until_the_day_is_over():
    """Active yesterday, nothing yet today: the streak still stands."""
    days = [D(2026, 10, 28), D(2026, 10, 29)]
    result = compute(days, today=D(2026, 10, 30))
    assert result.current == 2
    assert not result.active_today


def test_streak_breaks_after_a_missed_day():
    days = [D(2026, 10, 28), D(2026, 10, 29)]
    assert compute(days, today=D(2026, 10, 31)).current == 0


def test_longest_is_remembered_after_a_break():
    days = [D(2026, 10, 1), D(2026, 10, 2), D(2026, 10, 3), D(2026, 10, 20)]
    result = compute(days, today=D(2026, 10, 20))
    assert (result.current, result.longest) == (1, 3)


def test_longest_run_finds_the_biggest_block():
    days = [
        D(2026, 1, 1),
        D(2026, 1, 2),
        D(2026, 2, 1),
        D(2026, 2, 2),
        D(2026, 2, 3),
        D(2026, 2, 4),
    ]
    assert longest_run(days) == 4


def test_longest_run_of_nothing_is_zero():
    assert longest_run([]) == 0


def test_duplicate_days_are_counted_once():
    days = [D(2026, 10, 29), D(2026, 10, 29), D(2026, 10, 28)]
    result = compute(days, today=D(2026, 10, 29))
    assert (result.current, result.total_days) == (2, 2)


def test_unsorted_input_is_handled():
    days = [D(2026, 10, 29), D(2026, 10, 27), D(2026, 10, 28)]
    assert compute(days, today=D(2026, 10, 29)).current == 3


def test_current_run_ignores_future_days():
    days = [D(2026, 10, 29), D(2026, 11, 5)]
    assert current_run(days, today=D(2026, 10, 29)) == 1


def test_current_run_spans_a_month_boundary():
    days = [D(2026, 10, 30), D(2026, 10, 31), D(2026, 11, 1)]
    assert current_run(days, today=D(2026, 11, 1)) == 3


def test_current_run_spans_a_leap_day():
    days = [D(2028, 2, 28), D(2028, 2, 29), D(2028, 3, 1)]
    assert current_run(days, today=D(2028, 3, 1)) == 3


def test_longest_can_exceed_current():
    days = [D(2026, 1, 1), D(2026, 1, 2), D(2026, 1, 3), D(2026, 3, 3)]
    result = compute(days, today=D(2026, 3, 3))
    assert result.current == 1 and result.longest == 3
