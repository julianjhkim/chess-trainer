"""Which day is it, for streak purposes.

The streak's day boundary is local midnight in Asia/Seoul regardless of where
the machine's clock thinks it is, so this module is the single place that
converts an instant into a calendar day. ``now`` is always injectable, which is
what makes the rest of the streak logic testable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Seoul"


def zone(name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    return ZoneInfo(name)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today(
    *, now: datetime | None = None, tz_name: str = DEFAULT_TIMEZONE
) -> date:
    """The current calendar date in the streak timezone."""
    moment = now or now_utc()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone(tz_name)).date()


def day_of(moment: datetime, *, tz_name: str = DEFAULT_TIMEZONE) -> date:
    """The streak-timezone calendar date containing ``moment``."""
    return today(now=moment, tz_name=tz_name)


def day_start(day: date, *, tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """Midnight at the start of ``day``, in the streak timezone."""
    return datetime.combine(day, datetime.min.time(), tzinfo=zone(tz_name))


def next_day_start(day: date, *, tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """When ``day`` ends; i.e. midnight at the start of the following day."""
    return day_start(day + timedelta(days=1), tz_name=tz_name)
