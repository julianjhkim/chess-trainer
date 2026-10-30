"""Repository for ``card_reviews``: one row per card answer.

Keeps a history of the drills -- what was graded, how many tries it took and
where the schedule landed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from chess_trainer.db.connection import query_all, query_value, transaction


@dataclass(frozen=True, slots=True)
class CardReview:
    card_id: int
    reviewed_on: date
    quality: int
    attempts: int
    used_show_answer: bool = False
    was_new: bool = False
    interval_days: int | None = None
    ef: float | None = None
    id: int | None = None
    reviewed_at: str | None = None

    @property
    def passed(self) -> bool:
        return self.quality >= 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row: sqlite3.Row) -> CardReview:
    return CardReview(
        id=row["id"],
        card_id=row["card_id"],
        reviewed_at=row["reviewed_at"],
        reviewed_on=date.fromisoformat(row["reviewed_on"]),
        quality=row["quality"],
        attempts=row["attempts"],
        used_show_answer=bool(row["used_show_answer"]),
        was_new=bool(row["was_new"]),
        interval_days=row["interval_days"],
        ef=row["ef"],
    )


def record(conn: sqlite3.Connection, review: CardReview) -> CardReview:
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO card_reviews (
                card_id, reviewed_at, reviewed_on, quality, attempts,
                used_show_answer, was_new, interval_days, ef
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.card_id,
                review.reviewed_at or _now(),
                review.reviewed_on.isoformat(),
                review.quality,
                review.attempts,
                int(review.used_show_answer),
                int(review.was_new),
                review.interval_days,
                review.ef,
            ),
        )
        new_id = int(cursor.lastrowid)
        rows = query_all(conn, "SELECT * FROM card_reviews WHERE id = ?", (new_id,))
    return _row(rows[0])


def for_card(conn: sqlite3.Connection, card_id: int) -> list[CardReview]:
    rows = query_all(
        conn,
        "SELECT * FROM card_reviews WHERE card_id = ? ORDER BY reviewed_at DESC, id DESC",
        (card_id,),
    )
    return [_row(r) for r in rows]


def recent(conn: sqlite3.Connection, limit: int = 50) -> list[CardReview]:
    rows = query_all(
        conn,
        "SELECT * FROM card_reviews ORDER BY reviewed_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [_row(r) for r in rows]


def answered_on(conn: sqlite3.Connection, day: date) -> int:
    return int(
        query_value(
            conn,
            "SELECT COUNT(*) FROM card_reviews WHERE reviewed_on = ?",
            (day.isoformat(),),
            default=0,
        )
    )


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM card_reviews", default=0))
