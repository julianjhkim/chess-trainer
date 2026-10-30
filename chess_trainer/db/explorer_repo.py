"""Repository for ``explorer_cache``.

The masters database barely changes, so every response is kept forever and the
app almost never goes back to the network. Keyed by EPD, because the explorer
is position-based: two transposing lines return identical data.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from chess_trainer.db.connection import query_one, query_value, transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(conn: sqlite3.Connection, epd: str) -> dict[str, Any] | None:
    """The cached response for a position, or ``None``."""
    row = query_one(conn, "SELECT response FROM explorer_cache WHERE epd = ?", (epd,))
    if row is None:
        return None
    try:
        payload = json.loads(row["response"])
    except ValueError:  # pragma: no cover - would mean a corrupted row
        return None
    return payload if isinstance(payload, dict) else None


def put(
    conn: sqlite3.Connection, epd: str, payload: dict[str, Any], total_games: int
) -> None:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO explorer_cache (epd, response, total_games, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (epd) DO UPDATE SET
                response = excluded.response,
                total_games = excluded.total_games,
                fetched_at = excluded.fetched_at
            """,
            (epd, json.dumps(payload, separators=(",", ":")), total_games, _now()),
        )


def has(conn: sqlite3.Connection, epd: str) -> bool:
    return query_one(conn, "SELECT 1 FROM explorer_cache WHERE epd = ?", (epd,)) is not None


def total_games(conn: sqlite3.Connection, epd: str) -> int | None:
    row = query_one(
        conn, "SELECT total_games FROM explorer_cache WHERE epd = ?", (epd,)
    )
    return int(row["total_games"]) if row else None


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM explorer_cache", default=0))
