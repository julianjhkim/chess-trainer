"""Repository for ``analysis_cache``: Stockfish results keyed by (fen, depth).

The engine is the slowest thing in the app, so every result is cached. Positions
are stored by full FEN, which means a transposition reached in a different game
is a cache hit too.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from chess_trainer.db.connection import query_one, query_value, transaction
from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.stockfish import EngineAnalysis


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(conn: sqlite3.Connection, fen: str, depth: int) -> EngineAnalysis | None:
    row = query_one(
        conn,
        "SELECT cp, mate, best_move, pv FROM analysis_cache WHERE fen = ? AND depth = ?",
        (fen, depth),
    )
    if row is None:
        return None
    return EngineAnalysis(
        fen=fen,
        depth=depth,
        evaluation=Eval(cp=row["cp"], mate=row["mate"]),
        best_move=row["best_move"],
        pv=tuple(row["pv"].split()) if row["pv"] else (),
    )


def put(conn: sqlite3.Connection, analysis: EngineAnalysis) -> None:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO analysis_cache (fen, depth, cp, mate, best_move, pv, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (fen, depth) DO UPDATE
                SET cp = excluded.cp,
                    mate = excluded.mate,
                    best_move = excluded.best_move,
                    pv = excluded.pv,
                    created_at = excluded.created_at
            """,
            (
                analysis.fen,
                analysis.depth,
                analysis.evaluation.cp,
                analysis.evaluation.mate,
                analysis.best_move,
                " ".join(analysis.pv) or None,
                _now(),
            ),
        )


def count(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COUNT(*) FROM analysis_cache", default=0))
