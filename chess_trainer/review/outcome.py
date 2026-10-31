"""Whether I won, drew or lost a game.

chess.com reports a result code per player (``win``, ``checkmated``,
``agreed``, ...); a pasted PGN only has its ``Result`` header. Either is
enough to say how the game went for me, which the review uses to congratulate
a clean win or draw.

Pure: result strings in, ``win`` / ``draw`` / ``loss`` (or None) out.
"""

from __future__ import annotations

WIN = "win"
DRAW = "draw"
LOSS = "loss"

#: chess.com's per-player codes for a drawn game; every other code but
#: ``win`` is a loss (checkmated, resigned, timeout, abandoned, ...).
CHESSCOM_DRAWS = frozenset(
    {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}
)


def from_chesscom(code: str | None) -> str | None:
    if not code:
        return None
    code = code.strip().lower()
    if code == "win":
        return WIN
    if code in CHESSCOM_DRAWS:
        return DRAW
    return LOSS


def from_pgn_result(result: str | None, my_colour: str) -> str | None:
    """``1-0`` / ``0-1`` / ``1/2-1/2`` from my side; None for ``*`` or nothing."""
    result = (result or "").strip()
    if result == "1/2-1/2":
        return DRAW
    if result in {"1-0", "0-1"}:
        white_won = result == "1-0"
        return WIN if white_won == (my_colour == "white") else LOSS
    return None


def my_outcome(my_result: str | None, pgn_result: str | None, my_colour: str) -> str | None:
    """chess.com's code when there is one, the PGN header otherwise."""
    return from_chesscom(my_result) or from_pgn_result(pgn_result, my_colour)
