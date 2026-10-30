"""Repository for ``games``: games fetched from chess.com or pasted as PGN.

Storing them means a review can be replayed without hitting the network again,
and the "newer than the last game I saw" check in step 2 has something to
compare against.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from chess_trainer.db.connection import query_all, query_one, query_value, transaction

#: Where a stored game came from.
SOURCE_CHESSCOM = "chesscom"
SOURCE_PASTE = "paste"


@dataclass(frozen=True, slots=True)
class StoredGame:
    id: str
    pgn: str
    my_color: str
    url: str | None = None
    white_username: str | None = None
    black_username: str | None = None
    white_result: str | None = None
    black_result: str | None = None
    time_class: str | None = None
    rules: str | None = None
    end_time: int | None = None
    source: str = SOURCE_CHESSCOM
    fetched_at: str | None = None

    @property
    def my_color_is_white(self) -> bool:
        return self.my_color == "white"

    @property
    def opponent(self) -> str | None:
        return self.black_username if self.my_color_is_white else self.white_username

    @property
    def my_result(self) -> str | None:
        return self.white_result if self.my_color_is_white else self.black_result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row: sqlite3.Row) -> StoredGame:
    return StoredGame(
        id=row["id"],
        pgn=row["pgn"],
        my_color=row["my_color"],
        url=row["url"],
        white_username=row["white_username"],
        black_username=row["black_username"],
        white_result=row["white_result"],
        black_result=row["black_result"],
        time_class=row["time_class"],
        rules=row["rules"],
        end_time=row["end_time"],
        source=row["source"],
        fetched_at=row["fetched_at"],
    )


def upsert(conn: sqlite3.Connection, game: StoredGame) -> StoredGame:
    """Store a game, replacing any existing row with the same id."""
    fetched_at = game.fetched_at or _now()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO games (
                id, url, pgn, my_color, white_username, black_username,
                white_result, black_result, time_class, rules, end_time,
                source, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                url = excluded.url,
                pgn = excluded.pgn,
                my_color = excluded.my_color,
                white_username = excluded.white_username,
                black_username = excluded.black_username,
                white_result = excluded.white_result,
                black_result = excluded.black_result,
                time_class = excluded.time_class,
                rules = excluded.rules,
                end_time = excluded.end_time,
                source = excluded.source
            """,
            (
                game.id,
                game.url,
                game.pgn,
                game.my_color,
                game.white_username,
                game.black_username,
                game.white_result,
                game.black_result,
                game.time_class,
                game.rules,
                game.end_time,
                game.source,
                fetched_at,
            ),
        )
    stored = get(conn, game.id)
    assert stored is not None  # just inserted
    return stored


def get(conn: sqlite3.Connection, game_id: str) -> StoredGame | None:
    row = query_one(conn, "SELECT * FROM games WHERE id = ?", (game_id,))
    return _row(row) if row else None


def exists(conn: sqlite3.Connection, game_id: str) -> bool:
    return query_one(conn, "SELECT 1 FROM games WHERE id = ?", (game_id,)) is not None


def latest(conn: sqlite3.Connection) -> StoredGame | None:
    """The most recently played game.

    Ordered by when the game ended, falling back to when we fetched it, so a
    pasted PGN without a date still sorts sensibly.
    """
    row = query_one(
        conn,
        """
        SELECT * FROM games
        ORDER BY COALESCE(end_time, 0) DESC, fetched_at DESC
        LIMIT 1
        """,
    )
    return _row(row) if row else None


def recent(conn: sqlite3.Connection, limit: int = 10) -> list[StoredGame]:
    rows = query_all(
        conn,
        """
        SELECT * FROM games
        ORDER BY COALESCE(end_time, 0) DESC, fetched_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_row(r) for r in rows]


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM games", default=0))
