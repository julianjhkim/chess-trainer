"""Walking a game into a stream of positions.

Each entry pairs the position *before* a move with the position *after* it,
which is exactly what classifying that move needs: the evaluation before and
the evaluation after, both read from the mover's perspective.

Pure: no engine, no database.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_trainer.pgn.parse import ParsedGame


@dataclass(frozen=True, slots=True)
class PositionMove:
    """One move, with the positions either side of it."""

    #: 0-based index into the game's move list.
    ply: int
    #: 1-based full move number, as printed in a PGN.
    move_number: int
    fen_before: str
    fen_after: str
    uci: str
    san: str
    mover_is_white: bool

    @property
    def mover_colour(self) -> str:
        return "white" if self.mover_is_white else "black"

    @property
    def move_label(self) -> str:
        """How the move is written in a game score, e.g. ``12...Qd4``."""
        separator = "." if self.mover_is_white else "..."
        return f"{self.move_number}{separator}{self.san}"


def walk(ucis: list[str], start_fen: str = chess.STARTING_FEN) -> list[PositionMove]:
    """Replay a line of UCI moves, recording the position around each one."""
    board = chess.Board(start_fen)
    positions: list[PositionMove] = []

    for ply, uci in enumerate(ucis):
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"{uci} is illegal at ply {ply}")

        fen_before = board.fen()
        san = board.san(move)
        mover_is_white = board.turn == chess.WHITE
        move_number = board.fullmove_number
        board.push(move)

        positions.append(
            PositionMove(
                ply=ply,
                move_number=move_number,
                fen_before=fen_before,
                fen_after=board.fen(),
                uci=uci,
                san=san,
                mover_is_white=mover_is_white,
            )
        )

    return positions


def from_parsed(parsed: ParsedGame) -> list[PositionMove]:
    """Positions for a parsed PGN."""
    return walk(parsed.ucis, parsed.start_fen)


def line_up_to(positions: list[PositionMove], ply: int) -> list[str]:
    """The UCI moves played before ``ply``, for replaying up to that position."""
    return [position.uci for position in positions if position.ply < ply]
