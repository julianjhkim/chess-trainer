"""Finding the puzzles in one of my games, the way Lichess finds its own.

The engine walks every move of the game, both sides'. A move that cost its
player at least a mistake's worth of win % (``classify``: 20 points) is a
mistake to punish. The puzzle starts right after it, played by the side that
can punish it: my opponent's side when the mistake was mine (that is how I
learn why my move was bad, whether or not they found the punishment), my own
side when it was theirs (whether or not I found it).

The punishing move must be clearly the only good one (``puzzle.is_only_move``)
-- then even a single move is a puzzle; otherwise there is nothing fair to
ask, and the mistake is reported but skipped. The line goes on while each
next move is an only move too (``puzzle.build_line``).

``scan_game`` asks the engine (through the analysis cache) and reports progress
through a callback; it can be cancelled between moves.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from chess_trainer.engine import analysis
from chess_trainer.engine.classify import classify
from chess_trainer.engine.stockfish import Analyser
from chess_trainer.engine.winpct import win_percent_drop
from chess_trainer.inaccuracies import puzzle
from chess_trainer.pgn import my_moves
from chess_trainer.pgn.positions import PositionMove

#: A move losing at least this much win % for its player is worth punishing:
#: mistakes and blunders (the user's choice), not inaccuracies.
MIN_DROP = 20.0


@dataclass(frozen=True, slots=True)
class FoundPuzzle:
    """A mistake, and the forced punishment that starts right after it."""

    slip: PositionMove
    #: Whether the mistake was mine (then the puzzle is played as my opponent).
    mine: bool
    win_percent_drop: float
    classification: str
    line: tuple[str, ...]

    @property
    def solver_colour(self) -> str:
        return "black" if self.slip.mover_is_white else "white"

    @property
    def solver_moves(self) -> int:
        return (len(self.line) + 1) // 2


@dataclass(slots=True)
class ScanResult:
    found: list[FoundPuzzle] = field(default_factory=list)
    #: Mistakes with no single clear punishment: not puzzles.
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
    is called after each move is checked."""
    result = ScanResult()
    for done, move in enumerate(positions, start=1):
        if cancelled():
            raise ScanCancelled
        found = _punishment(conn, engine, move, depth, my_colour)
        if isinstance(found, FoundPuzzle):
            result.found.append(found)
        elif found is not None:
            result.skipped.append(move)
        if on_progress is not None:
            on_progress(done, len(positions))
    return result


def _punishment(
    conn: sqlite3.Connection,
    engine: Analyser,
    move: PositionMove,
    depth: int,
    my_colour: str,
) -> FoundPuzzle | bool | None:
    """The puzzle after a mistake; ``False`` for a mistake with no clear
    punishment; ``None`` for a move that was not a mistake."""
    before = analysis.analyse(conn, engine, move.fen_before, depth)
    if before.best_move is None or before.best_move == move.uci:
        return None
    after = analysis.analyse(conn, engine, move.fen_after, depth)
    drop = win_percent_drop(
        before.evaluation, after.evaluation, mover_is_white=move.mover_is_white
    )
    if drop < MIN_DROP:
        return None
    if after.best_move is None:  # the mistake ended the game
        return None
    line = puzzle.build_line(
        conn, engine, move.fen_after, depth,
        first_move=after.best_move, first_must_be_only=True,
    )
    if not line:
        return False
    return FoundPuzzle(
        slip=move,
        mine=my_moves.is_mine(move, my_colour),
        win_percent_drop=drop,
        classification=classify(drop).value,
        line=line,
    )
