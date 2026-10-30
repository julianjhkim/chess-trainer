"""Repository for ``game_reviews``: a light history of completed reviews.

One row per review: which game, when, where the first inaccuracy was, what was
played versus what the engine wanted, how many attempts it took and whether the
answer was revealed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from chess_trainer.db.connection import query_all, query_one, query_value, transaction
from chess_trainer.engine.eval_types import Eval


@dataclass(frozen=True, slots=True)
class GameReview:
    game_id: str
    depth: int
    reviewed_on: date
    attempts: int = 0
    used_show_answer: bool = False
    #: None throughout when the game contained no inaccuracy.
    first_inaccuracy_ply: int | None = None
    my_move_uci: str | None = None
    my_move_san: str | None = None
    classification: str | None = None
    best_move_uci: str | None = None
    best_move_san: str | None = None
    eval_before: Eval | None = None
    eval_after: Eval | None = None
    win_percent_drop: float | None = None
    id: int | None = None
    reviewed_at: str | None = None

    @property
    def found_an_inaccuracy(self) -> bool:
        return self.first_inaccuracy_ply is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _eval_of(cp: int | None, mate: int | None) -> Eval | None:
    if cp is None and mate is None:
        return None
    return Eval(cp=cp, mate=mate)


def _row(row: sqlite3.Row) -> GameReview:
    return GameReview(
        id=row["id"],
        game_id=row["game_id"],
        depth=row["depth"],
        reviewed_at=row["reviewed_at"],
        reviewed_on=date.fromisoformat(row["reviewed_on"]),
        first_inaccuracy_ply=row["first_inaccuracy_ply"],
        my_move_uci=row["my_move_uci"],
        my_move_san=row["my_move_san"],
        classification=row["classification"],
        best_move_uci=row["best_move_uci"],
        best_move_san=row["best_move_san"],
        eval_before=_eval_of(row["eval_before_cp"], row["eval_before_mate"]),
        eval_after=_eval_of(row["eval_after_cp"], row["eval_after_mate"]),
        win_percent_drop=row["win_percent_drop"],
        attempts=row["attempts"],
        used_show_answer=bool(row["used_show_answer"]),
    )


def record(conn: sqlite3.Connection, review: GameReview) -> GameReview:
    """Append a review to the history and return it with its assigned id."""
    before = review.eval_before
    after = review.eval_after
    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO game_reviews (
                game_id, reviewed_at, reviewed_on, depth, first_inaccuracy_ply,
                my_move_uci, my_move_san, classification,
                best_move_uci, best_move_san,
                eval_before_cp, eval_before_mate, eval_after_cp, eval_after_mate,
                win_percent_drop, attempts, used_show_answer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.game_id,
                review.reviewed_at or _now(),
                review.reviewed_on.isoformat(),
                review.depth,
                review.first_inaccuracy_ply,
                review.my_move_uci,
                review.my_move_san,
                review.classification,
                review.best_move_uci,
                review.best_move_san,
                before.cp if before else None,
                before.mate if before else None,
                after.cp if after else None,
                after.mate if after else None,
                review.win_percent_drop,
                review.attempts,
                int(review.used_show_answer),
            ),
        )
        new_id = int(cursor.lastrowid)
    stored = get(conn, new_id)
    assert stored is not None  # just inserted
    return stored


def get(conn: sqlite3.Connection, review_id: int) -> GameReview | None:
    row = query_one(conn, "SELECT * FROM game_reviews WHERE id = ?", (review_id,))
    return _row(row) if row else None


def for_game(conn: sqlite3.Connection, game_id: str) -> list[GameReview]:
    """Every review of one game, newest first."""
    rows = query_all(
        conn,
        "SELECT * FROM game_reviews WHERE game_id = ? ORDER BY reviewed_at DESC, id DESC",
        (game_id,),
    )
    return [_row(r) for r in rows]


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[GameReview]:
    rows = query_all(
        conn,
        "SELECT * FROM game_reviews ORDER BY reviewed_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [_row(r) for r in rows]


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM game_reviews", default=0))
