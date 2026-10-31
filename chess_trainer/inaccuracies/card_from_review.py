"""Turning a finished review into an inaccuracy card.

The card is the position before my first inaccuracy, oriented to my side, with
the engine's move as the answer and the move I actually played kept for the
result screen.

Pure: a review target in, a card out.
"""

from __future__ import annotations

import chess

from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard
from chess_trainer.review.review_session import ReviewTarget


def epd_of(fen: str) -> str:
    """The position without its move counters, so a repeat is the same card."""
    return chess.Board(fen).epd()


def card_from_review(
    target: ReviewTarget, *, game_id: str | None, my_colour: str, depth: int
) -> InaccuracyCard:
    return InaccuracyCard(
        epd=epd_of(target.fen_before),
        fen=target.fen_before,
        game_id=game_id,
        ply=target.ply,
        move_number=target.move_number,
        my_colour=my_colour,
        last_move_uci=target.replay_ucis[-1] if target.replay_ucis else None,
        my_move_uci=target.my_move_uci,
        my_move_san=target.my_move_san,
        best_move_uci=target.best_move_uci,
        best_move_san=target.best_move_san,
        classification=target.classification,
        win_percent_drop=target.win_percent_drop,
        depth=depth,
    )
