"""Cached position analysis.

Sits between the app and :mod:`chess_trainer.engine.stockfish`, consulting the
SQLite cache first. Takes an :class:`~chess_trainer.engine.stockfish.Analyser`
rather than a concrete engine, so it can be tested with a fake.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator

from chess_trainer.db import analysis_repo
from chess_trainer.engine.stockfish import Analyser, EngineAnalysis


def analyse(
    conn: sqlite3.Connection,
    engine: Analyser,
    fen: str,
    depth: int,
    *,
    use_cache: bool = True,
) -> EngineAnalysis:
    """Analyse one position, reading through the cache."""
    if use_cache:
        cached = analysis_repo.get(conn, fen, depth)
        if cached is not None:
            return cached
    result = engine.analyse(fen, depth)
    analysis_repo.put(conn, result)
    return result


def analyse_many(
    conn: sqlite3.Connection,
    engine: Analyser,
    fens: Iterable[str],
    depth: int,
) -> Iterator[EngineAnalysis]:
    """Analyse positions lazily, in order.

    A generator on purpose: the game review walks the game until it finds the
    first inaccuracy, and stops the engine work there.
    """
    for fen in fens:
        yield analyse(conn, engine, fen, depth)


def cached_only(
    conn: sqlite3.Connection, fen: str, depth: int
) -> EngineAnalysis | None:
    """Look up a position without ever starting the engine."""
    return analysis_repo.get(conn, fen, depth)
