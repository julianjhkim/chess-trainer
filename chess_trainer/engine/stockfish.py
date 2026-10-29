"""Stockfish process wrapper.

This is the only module that talks to the engine binary. It is synchronous and
guarded by a lock, because a UCI engine handles one search at a time; async
callers should hand work to a thread (see :mod:`chess_trainer.api.deps`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import chess
import chess.engine

from chess_trainer.engine.eval_types import Eval


@dataclass(frozen=True, slots=True)
class EngineAnalysis:
    """The engine's verdict on one position, at one depth."""

    fen: str
    depth: int
    evaluation: Eval
    best_move: str | None  # UCI, or None in a terminal position


class Analyser(Protocol):
    """What the rest of the app needs from an engine.

    Declared as a Protocol so tests can substitute a fake without a subprocess.
    """

    def analyse(
        self, fen: str, depth: int, *, root_moves: list[str] | None = None
    ) -> EngineAnalysis: ...


class EngineNotAvailable(RuntimeError):
    """Raised when the Stockfish binary cannot be found or started."""


def _score_to_eval(score: chess.engine.PovScore) -> Eval:
    """Convert python-chess's score object into our White's-view Eval."""
    white = score.white()
    mate = white.mate()
    if mate is not None:
        # A mate distance of 0 means mate is already on the board. Represent it
        # as "mate in 1 for the side that delivered it" so Eval stays valid.
        if mate == 0:
            mate = 1 if white.score(mate_score=1) > 0 else -1
        return Eval(mate=mate)
    cp = white.score()
    assert cp is not None
    return Eval(cp=cp)


class StockfishEngine:
    """A long-lived Stockfish process."""

    def __init__(
        self,
        path: Path | str,
        *,
        threads: int | None = None,
        hash_mb: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.threads = threads
        self.hash_mb = hash_mb
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._engine is not None:
            return
        if not self.path.exists():
            raise EngineNotAvailable(
                f"Stockfish not found at {self.path}. Install it "
                "(`brew install stockfish`) or set CHESS_TRAINER_STOCKFISH_PATH."
            )
        try:
            engine = chess.engine.SimpleEngine.popen_uci(str(self.path))
        except OSError as exc:
            raise EngineNotAvailable(f"Could not start Stockfish at {self.path}: {exc}") from exc

        options: dict[str, int] = {}
        if self.threads is not None:
            options["Threads"] = self.threads
        if self.hash_mb is not None:
            options["Hash"] = self.hash_mb
        if options:
            engine.configure(options)
        self._engine = engine

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.quit()
                self._engine = None

    def __enter__(self) -> "StockfishEngine":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def is_running(self) -> bool:
        return self._engine is not None

    # -- analysis --------------------------------------------------------
    def analyse(
        self, fen: str, depth: int, *, root_moves: list[str] | None = None
    ) -> EngineAnalysis:
        """Search ``fen`` to ``depth`` and report the score and best move.

        ``root_moves`` restricts the search to those UCI moves, which is how we
        break ties between equally popular opening moves.
        """
        board = chess.Board(fen)
        if board.is_game_over():
            return EngineAnalysis(
                fen=fen,
                depth=depth,
                evaluation=_terminal_eval(board),
                best_move=None,
            )

        limit = chess.engine.Limit(depth=depth)
        moves = [chess.Move.from_uci(m) for m in root_moves] if root_moves else None

        with self._lock:
            if self._engine is None:
                self.start()
            assert self._engine is not None
            info = self._engine.analyse(board, limit, root_moves=moves)

        score = info.get("score")
        if score is None:
            raise EngineNotAvailable("Stockfish returned no score")
        pv = info.get("pv") or []
        best = pv[0].uci() if pv else None
        return EngineAnalysis(
            fen=fen, depth=depth, evaluation=_score_to_eval(score), best_move=best
        )


def _terminal_eval(board: chess.Board) -> Eval:
    """Evaluation of a finished position, from White's perspective."""
    outcome = board.outcome()
    if outcome is not None and outcome.winner is not None:
        # Mate is on the board: credit it to the winner as a mate-in-1 marker.
        return Eval(mate=1 if outcome.winner == chess.WHITE else -1)
    return Eval(cp=0)
