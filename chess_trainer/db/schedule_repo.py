"""Repository for ``card_schedule``: the SM-2 state of each card.

A card with no row here has never been answered, which is what makes it "new".
Due dates are Asia/Seoul calendar dates, matching the streak's day boundary.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from chess_trainer.db.connection import query_all, query_one, query_value, transaction
from chess_trainer.db.cards_repo import STATUS_ACTIVE, CardRow, _row as _card_row


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    card_id: int
    n: int
    ef: float
    interval_days: int
    due_on: date
    last_reviewed_on: date | None = None
    reps: int = 0
    lapses: int = 0

    def is_due(self, today: date) -> bool:
        return self.due_on <= today


def _row(row: sqlite3.Row) -> ScheduleRow:
    return ScheduleRow(
        card_id=row["card_id"],
        n=row["n"],
        ef=row["ef"],
        interval_days=row["interval_days"],
        due_on=date.fromisoformat(row["due_on"]),
        last_reviewed_on=(
            date.fromisoformat(row["last_reviewed_on"])
            if row["last_reviewed_on"]
            else None
        ),
        reps=row["reps"],
        lapses=row["lapses"],
    )


def get(conn: sqlite3.Connection, card_id: int) -> ScheduleRow | None:
    row = query_one(conn, "SELECT * FROM card_schedule WHERE card_id = ?", (card_id,))
    return _row(row) if row else None


def upsert(conn: sqlite3.Connection, schedule: ScheduleRow) -> ScheduleRow:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO card_schedule (
                card_id, n, ef, interval_days, due_on, last_reviewed_on, reps, lapses
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (card_id) DO UPDATE SET
                n = excluded.n,
                ef = excluded.ef,
                interval_days = excluded.interval_days,
                due_on = excluded.due_on,
                last_reviewed_on = excluded.last_reviewed_on,
                reps = excluded.reps,
                lapses = excluded.lapses
            """,
            (
                schedule.card_id,
                schedule.n,
                schedule.ef,
                schedule.interval_days,
                schedule.due_on.isoformat(),
                schedule.last_reviewed_on.isoformat()
                if schedule.last_reviewed_on
                else None,
                schedule.reps,
                schedule.lapses,
            ),
        )
    stored = get(conn, schedule.card_id)
    assert stored is not None  # just inserted
    return stored


def due_cards(
    conn: sqlite3.Connection, today: date, *, limit: int | None = None
) -> list[tuple[CardRow, ScheduleRow]]:
    """Cards due on or before ``today``, oldest due date first.

    Ties on the due date are broken by how long the card has been waiting and
    then by queue order, so the sequence is deterministic.
    """
    # s.card_id is needed as well as c.*: the schedule row is built from the
    # same result row, and cards.id is not called card_id.
    sql = """
        SELECT c.*, s.card_id, s.n, s.ef, s.interval_days, s.due_on,
               s.last_reviewed_on, s.reps, s.lapses
        FROM card_schedule s
        JOIN cards c ON c.id = s.card_id
        WHERE s.due_on <= ? AND c.status = ?
        ORDER BY s.due_on, c.depth, c.queue_seq
    """
    params: tuple[object, ...] = (today.isoformat(), STATUS_ACTIVE)
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)
    rows = query_all(conn, sql, params)
    return [(_card_row(r), _row(r)) for r in rows]


def next_due(
    conn: sqlite3.Connection, today: date
) -> tuple[CardRow, ScheduleRow] | None:
    found = due_cards(conn, today, limit=1)
    return found[0] if found else None


def count_due(conn: sqlite3.Connection, today: date) -> int:
    return int(
        query_value(
            conn,
            """
            SELECT COUNT(*) FROM card_schedule s
            JOIN cards c ON c.id = s.card_id
            WHERE s.due_on <= ? AND c.status = ?
            """,
            (today.isoformat(), STATUS_ACTIVE),
            default=0,
        )
    )


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM card_schedule", default=0))
