"""The puzzle line of a slip, the way Lichess builds its puzzles.

From the card's position, Stockfish plays the line out. The first move is the
card's answer, the engine's top move, whether or not it is the only good one
(it is already judged strictly). Each of my moves after it must be an *only
move*: the engine's best has to beat its second best by at least
``ONLY_MOVE_MARGIN`` points of win % for me (or mate when nothing else does,
or be the only legal move). The opponent's replies are the engine's best,
played for me. The line ends on one of my moves -- at mate, or at the first
point where my next move is no longer the only one -- with no length limit
beyond a safety guard against endless lines.

A slip with no forced follow-up stays a one-move card, as before.

``is_only_move``, ``accepts`` and ``reward`` are pure; ``build_line`` asks the
engine.
"""

from __future__ import annotations

import sqlite3

import chess

from chess_trainer.engine import analysis
from chess_trainer.engine import best_move as best_move_module
from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.stockfish import Analyser
from chess_trainer.engine.winpct import win_percent

#: How much better (win %, for the mover) the best move must be than the next.
ONLY_MOVE_MARGIN = 10.0

#: Not a length limit: a guard so a line that never stops cannot run forever.
MAX_PLIES = 61


def is_only_move(best: Eval, second: Eval | None, *, white_to_move: bool) -> bool:
    """Whether the best move is the only good one (``second`` None: no other).

    A mate beats anything that is not a mate, however winning: once a position
    is won, win % saturates near 100 for several moves, but only one mates.
    """
    if second is None:
        return True
    best_pov = best.pov(white_to_move)
    second_pov = second.pov(white_to_move)
    if best_pov.mate is not None and best_pov.mate > 0:
        return second_pov.mate is None or second_pov.mate <= 0
    gap = win_percent(best, white_to_move=white_to_move) - win_percent(
        second, white_to_move=white_to_move
    )
    return gap >= ONLY_MOVE_MARGIN


#: Pawn units, for telling a clear win of material from a positional edge.
PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9,
}


def material(board: chess.Board, colour: chess.Color) -> int:
    """``colour``'s material minus the other side's, in pawns."""
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        total += value * len(board.pieces(piece_type, colour))
        total -= value * len(board.pieces(piece_type, not colour))
    return total


def reward(fen: str, moves: tuple[str, ...]) -> tuple[bool, int]:
    """What playing ``moves`` from ``fen`` brings the side to move there:
    whether it mates, and the material it wins (in pawns, maybe negative)."""
    board = chess.Board(fen)
    solver = board.turn
    before = material(board, solver)
    for uci in moves:
        board.push_uci(uci)
    return board.is_checkmate(), material(board, solver) - before


def position_after(fen: str, moves: tuple[str, ...]) -> str:
    board = chess.Board(fen)
    for uci in moves:
        board.push_uci(uci)
    return board.fen()


def mates(fen: str, uci: str) -> bool:
    """Whether a move gives checkmate."""
    board = chess.Board(fen)
    board.push_uci(uci)
    return board.is_checkmate()


def accepts(fen: str, expected: str, tried: str) -> bool:
    """Whether a tried move solves this step: the engine's move, or any mate
    when the engine's move mates (as on Lichess, every mate is a solution)."""
    if tried == expected:
        return True
    return mates(fen, expected) and mates(fen, tried)


def build_line(
    conn: sqlite3.Connection,
    engine: Analyser,
    fen: str,
    depth: int,
    *,
    first_move: str,
    first_must_be_only: bool = False,
) -> tuple[str, ...]:
    """The puzzle from ``fen``: the solver's moves and the replies, starting
    with ``first_move`` (the answer) and ending with one of the solver's moves.

    ``first_must_be_only`` holds the first move to the only-move test too, as
    a punishment puzzle must: if it fails there is no puzzle, ``()``.
    """
    board = chess.Board(fen)
    if first_must_be_only and not _only_move(conn, engine, board, first_move, depth):
        return ()
    line = [first_move]
    board.push_uci(first_move)

    while not board.is_game_over() and len(line) < MAX_PLIES:
        reply = analysis.analyse(conn, engine, board.fen(), depth).best_move
        if reply is None:
            break
        board.push_uci(reply)
        if board.is_game_over() or board.is_repetition(2):
            break
        mine = analysis.analyse(conn, engine, board.fen(), depth).best_move
        if mine is None or not _only_move(conn, engine, board, mine, depth):
            break
        line += [reply, mine]
        board.push_uci(mine)

    return tuple(line)


def _only_move(
    conn: sqlite3.Connection, engine: Analyser, board: chess.Board, move: str, depth: int
) -> bool:
    fen = board.fen()
    if mates(fen, move):
        return True  # the finishing blow: any mate is accepted
    others = [m.uci() for m in board.legal_moves if m.uci() != move]
    best = analysis.analyse(conn, engine, fen, depth)
    second = best_move_module.second_best(conn, engine, fen, depth, move, others)
    return is_only_move(
        best.evaluation,
        second.evaluation if second is not None else None,
        white_to_move=board.turn == chess.WHITE,
    )
