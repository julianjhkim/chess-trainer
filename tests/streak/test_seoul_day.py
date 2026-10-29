from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from chess_trainer.streak import seoul_day


def test_timezone_default_is_seoul():
    assert seoul_day.DEFAULT_TIMEZONE == "Asia/Seoul"


def test_seoul_is_nine_hours_ahead_of_utc():
    moment = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)
    assert moment.astimezone(seoul_day.zone()).hour == 9


def test_before_seoul_midnight_is_still_the_same_day():
    # 14:59 UTC == 23:59 KST on the 29th
    moment = datetime(2026, 10, 29, 14, 59, tzinfo=timezone.utc)
    assert seoul_day.today(now=moment) == date(2026, 10, 29)


def test_after_seoul_midnight_is_the_next_day():
    # 15:00 UTC == 00:00 KST on the 30th
    moment = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
    assert seoul_day.today(now=moment) == date(2026, 10, 30)


def test_naive_datetimes_are_treated_as_utc():
    naive = datetime(2026, 10, 29, 15, 0)
    assert seoul_day.today(now=naive) == date(2026, 10, 30)


def test_other_timezones_can_be_requested():
    moment = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
    assert seoul_day.today(now=moment, tz_name="UTC") == date(2026, 10, 29)


def test_day_of_matches_today():
    moment = datetime(2026, 5, 1, 3, 0, tzinfo=timezone.utc)
    assert seoul_day.day_of(moment) == seoul_day.today(now=moment)


def test_day_start_is_seoul_midnight():
    start = seoul_day.day_start(date(2026, 10, 29))
    assert (start.hour, start.minute) == (0, 0)
    assert start.utcoffset() == timedelta(hours=9)


def test_next_day_start_is_twenty_four_hours_later():
    day = date(2026, 10, 29)
    delta = seoul_day.next_day_start(day) - seoul_day.day_start(day)
    assert delta == timedelta(days=1)


def test_now_utc_is_timezone_aware():
    assert seoul_day.now_utc().tzinfo is not None


def test_today_without_now_uses_the_clock():
    assert isinstance(seoul_day.today(), date)
