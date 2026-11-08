"""Finding the puzzles in one of my games.

The engine walks every move I made. A move that cost me at least an
inaccuracy's worth of win % (``classify``) is a slip; from the position before
it, the engine's top move is the answer and ``puzzle.build_line`` plays the
line on. Only a slip whose answer starts a forced line of at least
``MIN_MY_MOVES`` of my moves becomes a puzzle -- the user chose "forced lines
only", so a slip with nothing forced after the answer is reported but skipped.

``scan_game`` asks the engine (through the analysis cache) and reports progress
through a callback; it can be cancelled between moves.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from chess_trainer.engine import analysis
from chess_trainer.engine.classify import Classification, classify
from chess_trainer.engine.stockfish import Analyser
from chess_trainer.engine.winpct import win_percent_drop
from chess_trainer.inaccuracies import puzzle
from chess_trainer.pgn import my_moves
from chess_trainer.pgn.positions import PositionMove

#: A puzzle asks at least this many of my moves (the answer and a forced one).
MIN_MY_MOVES = 2


@dataclass(frozen=True, slots=True)
class FoundPuzzle:
    """A slip of mine with a forced line after the engine's answer."""

    slip: PositionMove
    best_move_uci: str
    win_percent_drop: float
    classification: str
    line: tuple[str, ...]

    @property
    def my_moves(self) -> int:
        return (len(self.line) + 1) // 2


@dataclass(slots=True)
class ScanResult:
    found: list[FoundPuzzle] = field(default_factory=list)
    #: Slips with no forced line after the answer: not puzzles.
    skipped: list[PositionMove] = field(default_factory=list)


class ScanCancelled(Exception):
    """The scan was stopped before it finished."""


def scan_game(
    conn: sqlite3.Connection,
    engine: Analyser,
    positions: list[PositionMove],
    my_colour: str,
    depth: int,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> ScanResult:
    """Every puzzle in a game, in game order. ``on_progress(done, total)``
    is called after each of my moves is checked."""
    mine = my_moves.mine(positions, my_colour)
    result = ScanResult()
    for done, move in enumerate(mine, start=1):
        if cancelled():
            raise ScanCancelled
        slip = _slip(conn, engine, move, depth)
        if slip is not None:
            line = puzzle.build_line(
                conn, engine, move.fen_before, depth, first_move=slip[0]
            )
            if (len(line) + 1) // 2 >= MIN_MY_MOVES:
                result.found.append(
                    FoundPuzzle(
                        slip=move,
                        best_move_uci=slip[0],
                        win_percent_drop=slip[1],
                        classification=slip[2],
                        line=line,
                    )
                )
            else:
                result.skipped.append(move)
        if on_progress is not None:
            on_progress(done, len(mine))
    return result


def _slip(
    conn: sqlite3.Connection, engine: Analyser, move: PositionMove, depth: int
) -> tuple[str, float, str] | None:
    """For a slip: the engine's move, the win % it cost, and what kind of slip
    it was. ``None`` for a move that was fine."""
    before = analysis.analyse(conn, engine, move.fen_before, depth)
    if before.best_move is None or before.best_move == move.uci:
        return None
    after = analysis.analyse(conn, engine, move.fen_after, depth)
    drop = win_percent_drop(
        before.evaluation, after.evaluation, mover_is_white=move.mover_is_white
    )
    kind = classify(drop)
    if kind is Classification.GOOD:
        return None
    return before.best_move, drop, kind.value
