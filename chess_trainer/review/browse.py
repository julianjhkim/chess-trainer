"""Which of a game's moves the review lets me step through.

While the drill is open only the moves *before* my first inaccuracy are
browsable: the move I actually played there is the one I am being asked to
improve on, and anything after it is the game I have not yet earned back. Once
the review is over -- solved, revealed, or there was nothing to fix -- the whole
game is open, to the last move.

Pure: positions in, positions out.
"""

from __future__ import annotations

from chess_trainer.pgn.positions import PositionMove


def browsable_moves(
    positions: list[PositionMove],
    *,
    target_ply: int | None,
    finished: bool,
) -> list[PositionMove]:
    """The moves the review may show, in game order.

    ``target_ply`` is the ply of my first inaccuracy, or None when the game had
    none (in which case there is nothing to hide).
    """
    if finished or target_ply is None:
        return list(positions)
    return [position for position in positions if position.ply < target_ply]
