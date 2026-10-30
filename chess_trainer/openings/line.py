"""Lines of moves, and the positions they reach.

A card is identified by the position it stands for, and presented as the line
that reaches it. Pure: no database, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

START_FEN = chess.STARTING_FEN
WHITE = "white"
BLACK = "black"


@dataclass(frozen=True, slots=True)
class LinePosition:
    """A position reached by a line of moves."""

    ucis: tuple[str, ...]
    fen: str
    #: FEN without the halfmove/fullmove counters: the position's identity, so
    #: transpositions share one card.
    epd: str
    side_to_move: str

    @property
    def depth(self) -> int:
        return len(self.ucis)

    @property
    def line_uci(self) -> str:
        """The line as stored in the database: space-separated UCI."""
        return " ".join(self.ucis)

    @property
    def is_root(self) -> bool:
        return not self.ucis

    @property
    def given_move_uci(self) -> str | None:
        """The last move of the line: the one shown as an arrow."""
        return self.ucis[-1] if self.ucis else None


def parse_line(line_uci: str) -> tuple[str, ...]:
    """Split a stored line back into UCI moves."""
    return tuple(line_uci.split()) if line_uci.strip() else ()


def board_after(ucis: tuple[str, ...] | list[str]) -> chess.Board:
    """Replay a line from the start, raising ``ValueError`` on an illegal move."""
    board = chess.Board()
    for index, uci in enumerate(ucis):
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"{uci} is illegal at depth {index}")
        board.push(move)
    return board


def position_of(ucis: tuple[str, ...] | list[str]) -> LinePosition:
    """Build the :class:`LinePosition` for a line."""
    board = board_after(ucis)
    return LinePosition(
        ucis=tuple(ucis),
        fen=board.fen(),
        epd=board.epd(),
        side_to_move=WHITE if board.turn == chess.WHITE else BLACK,
    )


def root() -> LinePosition:
    """The start position, which is never itself a card."""
    return position_of(())


def extend(position: LinePosition, uci: str) -> LinePosition:
    """The position after playing ``uci`` in ``position``."""
    return position_of((*position.ucis, uci))


def san_of(fen: str, uci: str) -> str:
    """SAN for a move in a position, without applying it."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        raise ValueError(f"{uci} is not legal in {fen}")
    return board.san(move)


def sans_of_line(ucis: tuple[str, ...] | list[str]) -> list[str]:
    """SAN for each move of a line, in order."""
    board = chess.Board()
    sans: list[str] = []
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"{uci} is illegal in {board.fen()}")
        sans.append(board.san(move))
        board.push(move)
    return sans


def move_number_of(depth: int) -> int:
    """The full move number a move at ``depth`` (0-based) belongs to."""
    return depth // 2 + 1


def line_label(ucis: tuple[str, ...] | list[str]) -> str:
    """A line written as a game score, e.g. ``1.e4 c5 2.Nf3``."""
    sans = sans_of_line(ucis)
    parts: list[str] = []
    for index, san in enumerate(sans):
        if index % 2 == 0:
            parts.append(f"{move_number_of(index)}.{san}")
        else:
            parts.append(san)
    return " ".join(parts)
