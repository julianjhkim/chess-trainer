"""The names I play under, kept in ``app_state`` as a JSON list.

Edited from the app's top bar. The first time they are read, the list is seeded
from ``CHESS_TRAINER_CHESSCOM_USERNAME`` if that is set, so an existing `.env`
keeps working; from then on the stored list is the one that counts.
"""

from __future__ import annotations

import json
import sqlite3

from chess_trainer.db import state_repo
from chess_trainer.pgn.my_side import normalise

KEY = "my_usernames"


def get(conn: sqlite3.Connection, *, seed: str | None = None) -> list[str]:
    raw = state_repo.get(conn, KEY)
    if raw is None:
        names = normalise([seed]) if seed else []
        state_repo.set(conn, KEY, json.dumps(names))
        return names
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return normalise([v for v in value if isinstance(v, str)]) if isinstance(value, list) else []


def put(conn: sqlite3.Connection, names: list[str]) -> list[str]:
    cleaned = normalise(names)
    state_repo.set(conn, KEY, json.dumps(cleaned))
    return cleaned
