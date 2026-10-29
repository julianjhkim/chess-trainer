"""Recording activity and reading the streak back.

The I/O half of the streak feature: it owns the clock and the database, and
delegates the arithmetic to :mod:`chess_trainer.streak.streak`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chess_trainer.db import activity_repo
from chess_trainer.streak import seoul_day, streak as streak_math


def record_step(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    tz_name: str = seoul_day.DEFAULT_TIMEZONE,
) -> streak_math.Streak:
    """Note that a session step was completed, and return the updated streak."""
    day = seoul_day.today(now=now, tz_name=tz_name)
    activity_repo.record_step(conn, day)
    return get_streak(conn, now=now, tz_name=tz_name)


def get_streak(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    tz_name: str = seoul_day.DEFAULT_TIMEZONE,
) -> streak_math.Streak:
    days = activity_repo.active_days(conn)
    return streak_math.compute(days, today=seoul_day.today(now=now, tz_name=tz_name))
