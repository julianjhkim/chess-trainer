"""Database schema, expressed as an ordered list of migrations.

Each migration is applied once, in order, and the database's ``user_version``
pragma records how far it has got. Migrations are append-only: to change the
schema, add a new one rather than editing an existing one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from chess_trainer.db.connection import locked, transaction


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


#: Phase 1: engine eval cache, streak activity, and a small key/value store.
_M001 = Migration(
    version=1,
    name="core_state_activity_analysis",
    sql="""
    CREATE TABLE app_state (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- One row per day (Asia/Seoul) on which at least one step was completed.
    CREATE TABLE day_activity (
        day             TEXT PRIMARY KEY,   -- ISO date, Asia/Seoul
        steps_completed INTEGER NOT NULL DEFAULT 0,
        first_at        TEXT NOT NULL,      -- UTC timestamp
        last_at         TEXT NOT NULL       -- UTC timestamp
    );

    -- Stockfish results, keyed by position and search depth so a re-review of
    -- the same game costs nothing.
    CREATE TABLE analysis_cache (
        fen        TEXT NOT NULL,
        depth      INTEGER NOT NULL,
        cp         INTEGER,                 -- centipawns, White's perspective
        mate       INTEGER,                 -- mate distance, White's perspective
        best_move  TEXT,                    -- UCI
        created_at TEXT NOT NULL,
        PRIMARY KEY (fen, depth),
        CHECK (cp IS NOT NULL OR mate IS NOT NULL)
    );
    """,
)

MIGRATIONS: tuple[Migration, ...] = (_M001,)


def current_version(conn: sqlite3.Connection) -> int:
    with locked(conn):
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def pending(conn: sqlite3.Connection) -> list[Migration]:
    version = current_version(conn)
    return [m for m in MIGRATIONS if m.version > version]


def migrate(conn: sqlite3.Connection) -> list[Migration]:
    """Apply any outstanding migrations. Returns the ones that ran."""
    applied: list[Migration] = []
    for migration in pending(conn):
        with transaction(conn):
            conn.executescript(migration.sql)
            # PRAGMA does not accept parameter binding.
            conn.execute(f"PRAGMA user_version = {int(migration.version)}")
        applied.append(migration)
    return applied


def latest_version() -> int:
    return MIGRATIONS[-1].version if MIGRATIONS else 0
