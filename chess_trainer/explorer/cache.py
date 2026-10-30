"""Read-through cache in front of the explorer.

Sits between :mod:`chess_trainer.explorer.masters` and the network so a tree
that has been walked once never needs Lichess again.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol

from chess_trainer.db import explorer_repo


class MastersSource(Protocol):
    """What the cache needs from a client; a Protocol so tests can fake it."""

    def masters(self, fen: str, *, moves: int = ...) -> dict[str, Any]: ...


def fetch(
    conn: sqlite3.Connection,
    source: MastersSource,
    *,
    fen: str,
    epd: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return the masters record for a position, consulting the cache first."""
    if use_cache:
        cached = explorer_repo.get(conn, epd)
        if cached is not None:
            return cached

    payload = source.masters(fen)
    total = (
        int(payload.get("white") or 0)
        + int(payload.get("draws") or 0)
        + int(payload.get("black") or 0)
    )
    explorer_repo.put(conn, epd, payload, total)
    return payload


def cached_only(conn: sqlite3.Connection, epd: str) -> dict[str, Any] | None:
    """Look up a position without ever going to the network."""
    return explorer_repo.get(conn, epd)
