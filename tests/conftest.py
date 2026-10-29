"""Shared fixtures.

The guiding rule: nothing in the default test run touches the network or starts
Stockfish. Tests that genuinely need the real engine ask for the
``real_engine`` fixture, which skips when the binary is absent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from chess_trainer.config import Config
from chess_trainer.db import schema
from chess_trainer.db.connection import connect, open_memory_db
from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.stockfish import EngineAnalysis, StockfishEngine

STOCKFISH_PATH = Path("/opt/homebrew/bin/stockfish")
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.fixture
def conn() -> sqlite3.Connection:
    """A migrated in-memory database."""
    connection = open_memory_db()
    schema.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Path to a migrated on-disk database (needed when threads are involved)."""
    path = tmp_path / "test.db"
    connection = connect(path)
    schema.migrate(connection)
    connection.close()
    return path


class FakeEngine:
    """An :class:`Analyser` that returns canned results and counts calls.

    Scores default to a mild White edge; per-FEN overrides can be supplied.
    """

    def __init__(
        self,
        results: dict[str, Eval] | None = None,
        best_moves: dict[str, str] | None = None,
        default: Eval | None = None,
        default_best: str = "e2e4",
    ) -> None:
        self.results = results or {}
        self.best_moves = best_moves or {}
        self.default = default or Eval(cp=20)
        self.default_best = default_best
        self.calls: list[tuple[str, int, tuple[str, ...] | None]] = []

    def analyse(
        self, fen: str, depth: int, *, root_moves: list[str] | None = None
    ) -> EngineAnalysis:
        self.calls.append((fen, depth, tuple(root_moves) if root_moves else None))
        best = self.best_moves.get(fen, self.default_best)
        if root_moves:
            best = root_moves[0] if best not in root_moves else best
        return EngineAnalysis(
            fen=fen,
            depth=depth,
            evaluation=self.results.get(fen, self.default),
            best_move=best,
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def real_engine() -> StockfishEngine:
    """The actual Stockfish process; skipped when it is not installed."""
    if not STOCKFISH_PATH.exists():
        pytest.skip(f"Stockfish not installed at {STOCKFISH_PATH}")
    engine = StockfishEngine(STOCKFISH_PATH, threads=2, hash_mb=64)
    engine.start()
    yield engine
    engine.close()


@pytest.fixture
def config(db_path: Path) -> Config:
    """Config pointing at a temp database, with the browser disabled."""
    return Config(
        db_path=db_path,
        stockfish_path=STOCKFISH_PATH,
        engine_depth=8,
        open_browser=False,
        port=0,
    )
