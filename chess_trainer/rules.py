"""Chess rules helpers shared by every feature.

The browser must know which moves are legal in order to let a piece be dragged,
and the correctness of a drill answer must not be decided by the client. So
python-chess stays the single authority on rules and the frontend asks this
module (via ``/api/board``) rather than carrying its own rules engine.

Pure: no database, no network, no engine process.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

#: Chessground expects promotion roles spelled out.
PROMOTION_ROLES = {
    chess.QUEEN: "queen",
    chess.ROOK: "rook",
    chess.BISHOP: "bishop",
    chess.KNIGHT: "knight",
}
ROLE_TO_PIECE = {v: k for k, v in PROMOTION_ROLES.items()}
START_FEN = chess.STARTING_FEN


class IllegalMove(ValueError):
    """Raised when a move is not legal in the given position."""


@dataclass(frozen=True, slots=True)
class PositionState:
    """Everything the board needs to render and accept input."""

    fen: str
    turn: str  # "white" | "black"
    dests: dict[str, list[str]]  # chessground destination map
    in_check: bool
    game_over: bool
    outcome: str | None
    legal_ucis: list[str]


@dataclass(frozen=True, slots=True)
class MoveResult:
    fen_before: str
    fen_after: str
    uci: str
    san: str
    promotion: str | None
    is_capture: bool
    game_over: bool
    outcome: str | None


def board_of(fen: str) -> chess.Board:
    """Parse a FEN, raising ``ValueError`` with a readable message if invalid."""
    return chess.Board(fen)


def turn_name(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


def dests(board: chess.Board) -> dict[str, list[str]]:
    """Legal moves grouped by origin square, in chessground's ``dests`` shape."""
    grouped: dict[str, list[str]] = {}
    for move in board.legal_moves:
        origin = chess.square_name(move.from_square)
        target = chess.square_name(move.to_square)
        targets = grouped.setdefault(origin, [])
        if target not in targets:
            targets.append(target)
    return grouped


def outcome_text(board: chess.Board) -> str | None:
    """A short description of how the game ended, or ``None`` if it has not."""
    outcome = board.outcome()
    if outcome is None:
        return None
    if outcome.winner is chess.WHITE:
        return "White wins by " + outcome.termination.name.lower().replace("_", " ")
    if outcome.winner is chess.BLACK:
        return "Black wins by " + outcome.termination.name.lower().replace("_", " ")
    return "Draw by " + outcome.termination.name.lower().replace("_", " ")


def position_state(fen: str) -> PositionState:
    board = board_of(fen)
    return PositionState(
        fen=board.fen(),
        turn=turn_name(board),
        dests=dests(board),
        in_check=board.is_check(),
        game_over=board.is_game_over(),
        outcome=outcome_text(board),
        legal_ucis=[m.uci() for m in board.legal_moves],
    )


def needs_promotion(fen: str, origin: str, target: str) -> bool:
    """Whether moving ``origin``-``target`` is a pawn reaching the last rank."""
    board = board_of(fen)
    piece = board.piece_at(chess.parse_square(origin))
    if piece is None or piece.piece_type != chess.PAWN:
        return False
    last_rank = 7 if piece.color == chess.WHITE else 0
    return chess.square_rank(chess.parse_square(target)) == last_rank


def resolve_uci(
    fen: str, origin: str, target: str, promotion: str | None = None
) -> str:
    """Build a UCI string, appending a promotion piece when one is required.

    Defaults to a queen, which is what the board does when no choice is offered.
    """
    uci = f"{origin}{target}"
    if needs_promotion(fen, origin, target):
        piece = (promotion or "q").lower()[0]
        if piece not in {"q", "r", "b", "n"}:
            raise IllegalMove(f"Invalid promotion piece: {promotion!r}")
        uci += piece
    return uci


def apply_move(fen: str, uci: str) -> MoveResult:
    """Play ``uci`` in ``fen``, returning the SAN and resulting position."""
    board = board_of(fen)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError as exc:
        raise IllegalMove(f"Malformed move {uci!r}: {exc}") from exc
    if move not in board.legal_moves:
        raise IllegalMove(f"{uci} is not legal in this position")

    san = board.san(move)
    is_capture = board.is_capture(move)
    board.push(move)
    return MoveResult(
        fen_before=fen,
        fen_after=board.fen(),
        uci=uci,
        san=san,
        promotion=chess.piece_symbol(move.promotion) if move.promotion else None,
        is_capture=is_capture,
        game_over=board.is_game_over(),
        outcome=outcome_text(board),
    )


def san_of(fen: str, uci: str) -> str:
    """The SAN for a legal move, without applying it."""
    board = board_of(fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        raise IllegalMove(f"{uci} is not legal in this position")
    return board.san(move)


def fen_after_moves(ucis: list[str], start: str = START_FEN) -> str:
    """Replay a line of UCI moves from ``start`` and return the final FEN."""
    board = board_of(start)
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise IllegalMove(f"{uci} is not legal after {' '.join(ucis)}")
        board.push(move)
    return board.fen()
