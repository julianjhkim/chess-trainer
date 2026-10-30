"""Selecting the moves that are mine.

Only my moves get classified, so the review walks this filtered list. Pure.
"""

from __future__ import annotations

from chess_trainer.pgn.positions import PositionMove

WHITE = "white"


def is_mine(position: PositionMove, my_colour: str) -> bool:
    return position.mover_is_white == (my_colour == WHITE)


def mine(positions: list[PositionMove], my_colour: str) -> list[PositionMove]:
    """My moves, in game order."""
    return [p for p in positions if is_mine(p, my_colour)]


def opponents(positions: list[PositionMove], my_colour: str) -> list[PositionMove]:
    """My opponent's moves, in game order."""
    return [p for p in positions if not is_mine(p, my_colour)]
