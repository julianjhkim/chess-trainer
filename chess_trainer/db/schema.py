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

#: Phase 3: the opening explorer cache, the card tree, and SM-2 scheduling.
_M003 = Migration(
    version=3,
    name="explorer_cache_and_opening_cards",
    sql="""
    -- Cached masters-database responses. Keyed by EPD (a FEN without the
    -- halfmove/fullmove counters) because the explorer is position-based: two
    -- transposing lines return byte-identical data, and their FENs differ only
    -- in those counters.
    CREATE TABLE explorer_cache (
        epd         TEXT PRIMARY KEY,
        response    TEXT NOT NULL,      -- the raw JSON, so nothing is lost
        total_games INTEGER NOT NULL,   -- white+draws+black, for cheap queries
        fetched_at  TEXT NOT NULL
    );

    -- One row per position in the lazily grown tree. A position is one card,
    -- so the key is the EPD: a transposition does not become a second card.
    CREATE TABLE cards (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        epd            TEXT NOT NULL UNIQUE,
        fen            TEXT NOT NULL,
        line_uci       TEXT NOT NULL,     -- space-separated UCI from the start
        depth          INTEGER NOT NULL,
        parent_card_id INTEGER REFERENCES cards (id) ON DELETE CASCADE,
        side_to_move   TEXT NOT NULL CHECK (side_to_move IN ('white', 'black')),
        given_move_uci TEXT NOT NULL,     -- the move shown as an arrow
        given_move_san TEXT NOT NULL,
        -- 'dead_end' marks a position with too few games to be a card; it is
        -- kept so the "max depth reached" message has its stats.
        status         TEXT NOT NULL CHECK (status IN ('active', 'dead_end')),
        mode           TEXT CHECK (mode IN ('frequency', 'engine')),
        answer_uci     TEXT,
        answer_san     TEXT,
        tied_ucis      TEXT,              -- JSON array when a tie was broken
        opening_eco    TEXT,
        opening_name   TEXT,
        position_games INTEGER NOT NULL,
        queue_seq      INTEGER NOT NULL,  -- insertion order == breadth-first
        expanded_at    TEXT,              -- when this card's branches were built
        created_at     TEXT NOT NULL
    );

    CREATE INDEX cards_queue ON cards (status, depth, queue_seq);
    CREATE INDEX cards_parent ON cards (parent_card_id);

    -- SM-2 state. A card with no row here has never been answered, i.e. is new.
    CREATE TABLE card_schedule (
        card_id          INTEGER PRIMARY KEY REFERENCES cards (id) ON DELETE CASCADE,
        n                INTEGER NOT NULL DEFAULT 0,   -- ladder position; survives a lapse
        ef               REAL NOT NULL DEFAULT 2.5,    -- ease factor, floor 1.3
        interval_days    INTEGER NOT NULL DEFAULT 0,
        due_on           TEXT NOT NULL,                -- Asia/Seoul date
        last_reviewed_on TEXT,
        reps             INTEGER NOT NULL DEFAULT 0,
        lapses           INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX card_schedule_due ON card_schedule (due_on);

    -- One row per answer, for a history of the drills.
    CREATE TABLE card_reviews (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id          INTEGER NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
        reviewed_at      TEXT NOT NULL,
        reviewed_on      TEXT NOT NULL,
        quality          INTEGER NOT NULL,
        attempts         INTEGER NOT NULL,
        used_show_answer INTEGER NOT NULL DEFAULT 0,
        was_new          INTEGER NOT NULL DEFAULT 0,
        interval_days    INTEGER,
        ef               REAL
    );

    CREATE INDEX card_reviews_by_card ON card_reviews (card_id, reviewed_at DESC);
    """,
)

#: Review hints and explanations: the engine's whole line is kept alongside its
#: best move (space-separated UCI; NULL for results cached before this), and a
#: review records whether a hint was taken.
_M004 = Migration(
    version=4,
    name="engine_lines_and_review_hints",
    sql="""
    ALTER TABLE analysis_cache ADD COLUMN pv TEXT;
    ALTER TABLE game_reviews ADD COLUMN used_hint INTEGER NOT NULL DEFAULT 0;
    """,
)

MIGRATIONS: tuple[Migration, ...] = (_M001, _M002, _M003, _M004)


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
