"""Opening names, taken from the explorer rather than invented here.

The explorer reports an opening for a position, and for the position after each
candidate move. A card shows the name of the position it stands for, which is
the one attached to its given move by the parent's response -- so the name is
available without an extra request.
"""

from __future__ import annotations

from chess_trainer.explorer.explorer_types import MoveStat, Opening, PositionStats


def of_position(stats: PositionStats) -> Opening | None:
    """The opening of the position itself (``None`` at the start position)."""
    return stats.opening


def after_move(stats: PositionStats, uci: str) -> Opening | None:
    """The opening of the position reached by playing ``uci``."""
    move = stats.move(uci)
    return move.opening if move is not None else None


def of_move(move: MoveStat) -> Opening | None:
    return move.opening


def label(opening: Opening | None) -> str | None:
    """``"B20 Sicilian Defense"``, or ``None`` when unknown."""
    return opening.label if opening is not None else None


def pick(*candidates: Opening | None) -> Opening | None:
    """The first opening that is actually known.

    A deep or unusual position may have no opening of its own, in which case
    the name inherited from the parent line is the useful one.
    """
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None
