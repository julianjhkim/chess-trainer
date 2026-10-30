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

#: Phase 2: fetched games and a light history of the reviews done on them.
_M002 = Migration(
    version=2,
    name="games_and_game_reviews",
    sql="""
    -- Games fetched from chess.com, or pasted as PGN.
    CREATE TABLE games (
        id              TEXT PRIMARY KEY,   -- chess.com uuid, or a digest for pasted PGN
        url             TEXT,
        pgn             TEXT NOT NULL,
        my_color        TEXT NOT NULL CHECK (my_color IN ('white', 'black')),
        white_username  TEXT,
        black_username  TEXT,
        white_result    TEXT,
        black_result    TEXT,
        time_class      TEXT,
        rules           TEXT,
        end_time        INTEGER,            -- unix seconds; NULL if the PGN had no date
        source          TEXT NOT NULL CHECK (source IN ('chesscom', 'paste')),
        fetched_at      TEXT NOT NULL
    );

    CREATE INDEX games_by_recency ON games (end_time DESC, fetched_at DESC);

    -- One row per completed review, for a light history.
    CREATE TABLE game_reviews (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id              TEXT NOT NULL REFERENCES games (id) ON DELETE CASCADE,
        reviewed_at          TEXT NOT NULL,   -- UTC timestamp
        reviewed_on          TEXT NOT NULL,   -- Asia/Seoul calendar date
        depth                INTEGER NOT NULL,
        -- All of the following are NULL when the game held no inaccuracy.
        first_inaccuracy_ply INTEGER,
        my_move_uci          TEXT,
        my_move_san          TEXT,
        classification       TEXT,
        best_move_uci        TEXT,
        best_move_san        TEXT,
        eval_before_cp       INTEGER,
        eval_before_mate     INTEGER,
        eval_after_cp        INTEGER,
        eval_after_mate      INTEGER,
        win_percent_drop     REAL,
        attempts             INTEGER NOT NULL DEFAULT 0,
        used_show_answer     INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX game_reviews_by_game ON game_reviews (game_id, reviewed_at DESC);
    """,
)

MIGRATIONS: tuple[Migration, ...] = (_M001, _M002)


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
