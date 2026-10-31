"""Repositories for the inaccuracy cards: the cards, their schedule, the log.

``inaccuracy_cards`` holds one card per position -- the position before my
first inaccuracy in a reviewed game -- with the engine's move as the answer.
``inaccuracy_schedule`` is its SM-2 state (the same :class:`ScheduleRow` the
opening cards use), and ``inaccuracy_reviews`` one row per answer.

Every card is scheduled from the moment it is created, so unlike the opening
cards there is no "new" card here: a card is either due or waiting.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from chess_trainer.db.connection import query_all, query_one, query_value, transaction
from chess_trainer.db.schedule_repo import ScheduleRow, _row as _schedule_row


@dataclass(frozen=True, slots=True)
class InaccuracyCard:
    epd: str
    fen: str
    ply: int
    move_number: int
    my_colour: str
    my_move_uci: str
    my_move_san: str
    best_move_uci: str
    best_move_san: str
    classification: str
    depth: int
    game_id: str | None = None
    last_move_uci: str | None = None
    win_percent_drop: float | None = None
    id: int | None = None
    created_at: str | None = None

    @property
    def move_label(self) -> str:
        """My move as written in the game score, e.g. ``11.f4`` or ``11...Nf6``."""
        separator = "." if self.my_colour == "white" else "..."
        return f"{self.move_number}{separator}{self.my_move_san}"


@dataclass(frozen=True, slots=True)
class InaccuracyReview:
    card_id: int
    reviewed_on: date
    quality: int
    attempts: int
    used_show_answer: bool = False
    used_hint: bool = False
    interval_days: int | None = None
    ef: float | None = None
    id: int | None = None
    reviewed_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _card(row: sqlite3.Row) -> InaccuracyCard:
    return InaccuracyCard(
        id=row["id"],
        epd=row["epd"],
        fen=row["fen"],
        game_id=row["game_id"],
        ply=row["ply"],
        move_number=row["move_number"],
        my_colour=row["my_colour"],
        last_move_uci=row["last_move_uci"],
        my_move_uci=row["my_move_uci"],
        my_move_san=row["my_move_san"],
        best_move_uci=row["best_move_uci"],
        best_move_san=row["best_move_san"],
        classification=row["classification"],
        win_percent_drop=row["win_percent_drop"],
        depth=row["depth"],
        created_at=row["created_at"],
    )


def _review(row: sqlite3.Row) -> InaccuracyReview:
    return InaccuracyReview(
        id=row["id"],
        card_id=row["card_id"],
        reviewed_at=row["reviewed_at"],
        reviewed_on=date.fromisoformat(row["reviewed_on"]),
        quality=row["quality"],
        attempts=row["attempts"],
        used_show_answer=bool(row["used_show_answer"]),
        used_hint=bool(row["used_hint"]),
        interval_days=row["interval_days"],
        ef=row["ef"],
    )


# -- cards -------------------------------------------------------------------
def get(conn: sqlite3.Connection, card_id: int) -> InaccuracyCard | None:
    row = query_one(conn, "SELECT * FROM inaccuracy_cards WHERE id = ?", (card_id,))
    return _card(row) if row else None


def get_by_epd(conn: sqlite3.Connection, epd: str) -> InaccuracyCard | None:
    row = query_one(conn, "SELECT * FROM inaccuracy_cards WHERE epd = ?", (epd,))
    return _card(row) if row else None


def insert(conn: sqlite3.Connection, card: InaccuracyCard) -> InaccuracyCard:
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO inaccuracy_cards (
                epd, fen, game_id, ply, move_number, my_colour, last_move_uci,
                my_move_uci, my_move_san, best_move_uci, best_move_san,
                classification, win_percent_drop, depth, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card.epd,
                card.fen,
                card.game_id,
                card.ply,
                card.move_number,
                card.my_colour,
                card.last_move_uci,
                card.my_move_uci,
                card.my_move_san,
                card.best_move_uci,
                card.best_move_san,
                card.classification,
                card.win_percent_drop,
                card.depth,
                card.created_at or _now(),
            ),
        )
        new_id = int(cursor.lastrowid)
    stored = get(conn, new_id)
    assert stored is not None  # just inserted
    return stored


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM inaccuracy_cards", default=0))


# -- schedule ----------------------------------------------------------------
def get_schedule(conn: sqlite3.Connection, card_id: int) -> ScheduleRow | None:
    row = query_one(
        conn, "SELECT * FROM inaccuracy_schedule WHERE card_id = ?", (card_id,)
    )
    return _schedule_row(row) if row else None


def upsert_schedule(conn: sqlite3.Connection, schedule: ScheduleRow) -> ScheduleRow:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO inaccuracy_schedule (
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
    stored = get_schedule(conn, schedule.card_id)
    assert stored is not None  # just written
    return stored


def due_cards(
    conn: sqlite3.Connection, today: date, *, limit: int | None = None
) -> list[tuple[InaccuracyCard, ScheduleRow]]:
    """Cards due on or before ``today``: oldest due date first, then oldest card."""
    sql = """
        SELECT c.*, s.card_id, s.n, s.ef, s.interval_days, s.due_on,
               s.last_reviewed_on, s.reps, s.lapses
        FROM inaccuracy_schedule s
        JOIN inaccuracy_cards c ON c.id = s.card_id
        WHERE s.due_on <= ?
        ORDER BY s.due_on, c.id
    """
    params: tuple[object, ...] = (today.isoformat(),)
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)
    return [(_card(r), _schedule_row(r)) for r in query_all(conn, sql, params)]


def count_due(conn: sqlite3.Connection, today: date) -> int:
    return int(
        query_value(
            conn,
            "SELECT COUNT(*) FROM inaccuracy_schedule WHERE due_on <= ?",
            (today.isoformat(),),
            default=0,
        )
    )


def next_due_on(conn: sqlite3.Connection, today: date) -> date | None:
    """The earliest due date after ``today``, i.e. when the next card turns up."""
    value = query_value(
        conn,
        "SELECT MIN(due_on) FROM inaccuracy_schedule WHERE due_on > ?",
        (today.isoformat(),),
        default=None,
    )
    return date.fromisoformat(value) if value else None


# -- review log --------------------------------------------------------------
def record_review(conn: sqlite3.Connection, review: InaccuracyReview) -> InaccuracyReview:
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO inaccuracy_reviews (
                card_id, reviewed_at, reviewed_on, quality, attempts,
                used_show_answer, used_hint, interval_days, ef
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.card_id,
                review.reviewed_at or _now(),
                review.reviewed_on.isoformat(),
                review.quality,
                review.attempts,
                int(review.used_show_answer),
                int(review.used_hint),
                review.interval_days,
                review.ef,
            ),
        )
        new_id = int(cursor.lastrowid)
    row = query_one(conn, "SELECT * FROM inaccuracy_reviews WHERE id = ?", (new_id,))
    assert row is not None
    return _review(row)


def recent_reviews(conn: sqlite3.Connection, limit: int = 20) -> list[InaccuracyReview]:
    rows = query_all(
        conn,
        "SELECT * FROM inaccuracy_reviews ORDER BY reviewed_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [_review(r) for r in rows]
