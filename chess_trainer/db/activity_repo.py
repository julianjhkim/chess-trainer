"""Repository for ``day_activity``, the raw material for the streak.

A day is "active" once at least one session step has been completed on it. The
day is always an Asia/Seoul calendar date (see :mod:`chess_trainer.streak.seoul_day`);
this module stores whatever date string it is handed and does no timezone maths.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from chess_trainer.db.connection import query_all, query_one, query_value, transaction


@dataclass(frozen=True, slots=True)
class DayActivity:
    day: date
    steps_completed: int
    first_at: str
    last_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_activity(row: sqlite3.Row) -> DayActivity:
    return DayActivity(
        day=date.fromisoformat(row["day"]),
        steps_completed=row["steps_completed"],
        first_at=row["first_at"],
        last_at=row["last_at"],
    )


def record_step(conn: sqlite3.Connection, day: date, *, count: int = 1) -> DayActivity:
    """Mark ``count`` further completed steps on ``day``, creating the row if new."""
    now = _now()
    # One transaction covers the upsert and the read-back, so a concurrent
    # writer cannot slip a step in between them.
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO day_activity (day, steps_completed, first_at, last_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (day) DO UPDATE
                SET steps_completed = steps_completed + excluded.steps_completed,
                    last_at = excluded.last_at
            """,
            (day.isoformat(), count, now, now),
        )
        activity = get_day(conn, day)
    assert activity is not None  # just inserted
    return activity


def get_day(conn: sqlite3.Connection, day: date) -> DayActivity | None:
    row = query_one(
        conn, "SELECT * FROM day_activity WHERE day = ?", (day.isoformat(),)
    )
    return _row_to_activity(row) if row else None


def active_days(conn: sqlite3.Connection) -> list[date]:
    """Every day with at least one completed step, oldest first."""
    rows = query_all(
        conn, "SELECT day FROM day_activity WHERE steps_completed > 0 ORDER BY day"
    )
    return [date.fromisoformat(r["day"]) for r in rows]


def total_steps(conn: sqlite3.Connection) -> int:
    return int(
        query_value(
            conn, "SELECT COALESCE(SUM(steps_completed), 0) FROM day_activity", default=0
        )
    )
