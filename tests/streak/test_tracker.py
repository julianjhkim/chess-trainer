from __future__ import annotations

from datetime import date, datetime, timezone

from chess_trainer.db import activity_repo
from chess_trainer.streak import tracker

# 06:00 UTC on the 29th == 15:00 KST the same day.
SEOUL_29TH = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
# 16:00 UTC on the 29th == 01:00 KST on the 30th.
SEOUL_30TH = datetime(2026, 10, 29, 16, 0, tzinfo=timezone.utc)


def test_streak_starts_empty(conn):
    streak = tracker.get_streak(conn, now=SEOUL_29TH)
    assert (streak.current, streak.longest) == (0, 0)


def test_recording_a_step_starts_the_streak(conn):
    streak = tracker.record_step(conn, now=SEOUL_29TH)
    assert streak.current == 1
    assert streak.active_today


def test_the_recorded_day_uses_the_seoul_boundary(conn):
    tracker.record_step(conn, now=SEOUL_30TH)
    assert activity_repo.active_days(conn) == [date(2026, 10, 30)]


def test_several_steps_on_one_day_do_not_inflate_the_streak(conn):
    tracker.record_step(conn, now=SEOUL_29TH)
    streak = tracker.record_step(conn, now=SEOUL_29TH)
    assert streak.current == 1
    assert activity_repo.total_steps(conn) == 2


def test_consecutive_days_extend_the_streak(conn):
    tracker.record_step(conn, now=SEOUL_29TH)
    streak = tracker.record_step(conn, now=SEOUL_30TH)
    assert streak.current == 2
    assert streak.longest == 2


def test_timezone_override_is_respected(conn):
    tracker.record_step(conn, now=SEOUL_30TH, tz_name="UTC")
    assert activity_repo.active_days(conn) == [date(2026, 10, 29)]


def test_get_streak_does_not_record_anything(conn):
    tracker.get_streak(conn, now=SEOUL_29TH)
    assert activity_repo.active_days(conn) == []
