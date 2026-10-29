"""Repository for ``app_state``: a small key/value store for app-level facts.

Used for things that are not worth a table of their own, such as the id of the
most recent chess.com game we have already seen.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from chess_trainer.db.connection import query_one, transaction

#: Key under which the newest chess.com game id we have observed is stored.
LAST_SEEN_GAME_KEY = "last_seen_chesscom_game_id"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(conn: sqlite3.Connection, key: str) -> str | None:
    row = query_one(conn, "SELECT value FROM app_state WHERE key = ?", (key,))
    return row["value"] if row else None


def set(conn: sqlite3.Connection, key: str, value: str) -> None:  # noqa: A001
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                            updated_at = excluded.updated_at
            """,
            (key, value, _now()),
        )


def delete(conn: sqlite3.Connection, key: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM app_state WHERE key = ?", (key,))


def get_last_seen_game_id(conn: sqlite3.Connection) -> str | None:
    return get(conn, LAST_SEEN_GAME_KEY)


def set_last_seen_game_id(conn: sqlite3.Connection, game_id: str) -> None:
    set(conn, LAST_SEEN_GAME_KEY, game_id)
