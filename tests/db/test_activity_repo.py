from __future__ import annotations

from datetime import date

from chess_trainer.db import activity_repo

DAY = date(2026, 10, 29)


def test_no_activity_initially(conn):
    assert activity_repo.active_days(conn) == []
    assert activity_repo.get_day(conn, DAY) is None
    assert activity_repo.total_steps(conn) == 0


def test_record_step_creates_a_day(conn):
    activity = activity_repo.record_step(conn, DAY)
    assert activity.day == DAY
    assert activity.steps_completed == 1


def test_recording_twice_accumulates_on_the_same_day(conn):
    activity_repo.record_step(conn, DAY)
    activity = activity_repo.record_step(conn, DAY)
    assert activity.steps_completed == 2
    assert activity_repo.active_days(conn) == [DAY]


def test_first_at_is_kept_while_last_at_moves(conn):
    first = activity_repo.record_step(conn, DAY)
    second = activity_repo.record_step(conn, DAY)
    assert second.first_at == first.first_at


def test_count_argument_adds_several_steps(conn):
    assert activity_repo.record_step(conn, DAY, count=3).steps_completed == 3


def test_active_days_returns_oldest_first(conn):
    for day in (date(2026, 10, 5), date(2026, 10, 1), date(2026, 10, 3)):
        activity_repo.record_step(conn, day)
    assert activity_repo.active_days(conn) == [
        date(2026, 10, 1),
        date(2026, 10, 3),
        date(2026, 10, 5),
    ]


def test_total_steps_sums_across_days(conn):
    activity_repo.record_step(conn, DAY, count=2)
    activity_repo.record_step(conn, date(2026, 10, 30))
    assert activity_repo.total_steps(conn) == 3


def test_days_with_zero_steps_are_not_active(conn):
    conn.execute(
        "INSERT INTO day_activity (day, steps_completed, first_at, last_at)"
        " VALUES ('2026-10-01', 0, 'a', 'b')"
    )
    assert activity_repo.active_days(conn) == []
