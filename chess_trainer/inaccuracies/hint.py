"""What a hint gives away: which piece to move, and nothing more.

Pure: the position and the square of the piece the answer moves.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess


@dataclass(frozen=True, slots=True)
class Hint:
    #: The square the answer moves from, e.g. ``g1``.
    square: str
    #: The piece standing there, e.g. ``knight``.
    piece: str

    @property
    def text(self) -> str:
        return f"Move your {self.piece} on {self.square}."


def hint_for(fen: str, square: str) -> Hint:
    """Describe the piece on ``square`` in ``fen``."""
    piece = chess.Board(fen).piece_at(chess.parse_square(square))
    if piece is None:
        raise ValueError(f"No piece on {square}.")
    return Hint(square=square, piece=chess.piece_name(piece.piece_type))
