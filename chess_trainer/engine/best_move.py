"""Best-move queries, including the tie-break rule used by opening cards.

Two separate needs:

* game review: "is the move I played Stockfish's top choice at this depth?"
* opening cards: "several master moves are played equally often; which one does
  Stockfish prefer?" -- a search restricted to the tied moves.
"""

from __future__ import annotations

import sqlite3

from chess_trainer.db import analysis_repo
from chess_trainer.engine.analysis import analyse
from chess_trainer.engine.stockfish import Analyser, EngineAnalysis


def best_move(
    conn: sqlite3.Connection, engine: Analyser, fen: str, depth: int
) -> str | None:
    """Stockfish's top-1 move in UCI, or ``None`` in a terminal position."""
    return analyse(conn, engine, fen, depth).best_move


def is_best_move(
    conn: sqlite3.Connection,
    engine: Analyser,
    fen: str,
    depth: int,
    move_uci: str,
) -> bool:
    """Whether ``move_uci`` is the engine's top choice at ``depth``."""
    return best_move(conn, engine, fen, depth) == move_uci


def best_among(
    conn: sqlite3.Connection,
    engine: Analyser,
    fen: str,
    depth: int,
    candidates: list[str],
) -> str:
    """Pick the engine's favourite from ``candidates`` (UCI moves).

    With a single candidate the engine is not consulted at all. Results are
    cached under a synthetic key so repeated tie-breaks are free, keyed by the
    candidate set as well as the position.
    """
    if not candidates:
        raise ValueError("best_among needs at least one candidate move")
    if len(candidates) == 1:
        return candidates[0]

    ordered = sorted(candidates)
    cache_fen = f"{fen}|restricted:{','.join(ordered)}"
    cached = analysis_repo.get(conn, cache_fen, depth)
    if cached is not None and cached.best_move is not None:
        return cached.best_move

    result = engine.analyse(fen, depth, root_moves=ordered)
    chosen = result.best_move or ordered[0]
    analysis_repo.put(
        conn,
        EngineAnalysis(
            fen=cache_fen,
            depth=depth,
            evaluation=result.evaluation,
            best_move=chosen,
        ),
    )
    return chosen
