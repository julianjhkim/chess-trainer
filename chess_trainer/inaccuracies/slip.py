"""Finding the slip a card is made from, given a game and a move number.

I name the move I want to drill by its number in the game score -- "9" for my
ninth move, whether I was White or Black -- and this finds that move among the
game's positions. The card is the position before it, with that move as the
one I played; the answer is filled in later from the engine.

Pure: positions in, the slip (or a readable error) out.
"""

from __future__ import annotations

import chess

from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard
from chess_trainer.pgn.positions import PositionMove


class SlipNotFound(ValueError):
    """The game has no such move for my side."""


def epd_of(fen: str) -> str:
    """The position without its move counters, so a repeat is the same card."""
    return chess.Board(fen).epd()


def find_slip(
    positions: list[PositionMove], *, move_number: int, my_colour: str
) -> PositionMove:
    """My move numbered ``move_number`` in the game."""
    mine = [p for p in positions if p.mover_colour == my_colour]
    for position in mine:
        if position.move_number == move_number:
            return position
    side = "White" if my_colour == "white" else "Black"
    if not mine:
        raise SlipNotFound(f"{side} has no moves in this game.")
    first, last = mine[0].move_number, mine[-1].move_number
    raise SlipNotFound(
        f"{side} has no move {move_number} in this game: "
        f"your moves run from {first} to {last}."
    )


def moves_before(positions: list[PositionMove], slip: PositionMove) -> list[PositionMove]:
    """The moves leading to the slip, which can be stepped through while solving."""
    return [p for p in positions if p.ply < slip.ply]


def card_for(
    slip: PositionMove,
    *,
    game_id: str | None,
    my_colour: str,
    best_move_uci: str,
    classification: str,
    win_percent_drop: float | None,
    depth: int,
    previous: PositionMove | None,
) -> InaccuracyCard:
    """The card for a slip, once the engine has named the answer."""
    board = chess.Board(slip.fen_before)
    return InaccuracyCard(
        epd=epd_of(slip.fen_before),
        fen=slip.fen_before,
        game_id=game_id,
        ply=slip.ply,
        move_number=slip.move_number,
        my_colour=my_colour,
        last_move_uci=previous.uci if previous else None,
        my_move_uci=slip.uci,
        my_move_san=slip.san,
        best_move_uci=best_move_uci,
        best_move_san=board.san(chess.Move.from_uci(best_move_uci)),
        classification=classification,
        win_percent_drop=win_percent_drop,
        depth=depth,
    )
