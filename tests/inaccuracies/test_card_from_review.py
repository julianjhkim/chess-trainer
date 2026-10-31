from __future__ import annotations

from chess_trainer.engine.eval_types import Eval
from chess_trainer.inaccuracies.card_from_review import card_from_review, epd_of
from chess_trainer.pgn.positions import walk
from chess_trainer.review.review_session import ReviewTarget

LINE = ["e2e4", "e7e5", "g1f3"]


def target(ply: int = 2) -> ReviewTarget:
    position = walk(LINE)[ply]
    return ReviewTarget(
        ply=ply,
        move_number=position.move_number,
        move_label=position.move_label,
        fen_before=position.fen_before,
        replay_ucis=LINE[:ply],
        my_move_uci=position.uci,
        my_move_san=position.san,
        classification="mistake",
        eval_before=Eval(cp=30),
        eval_after=Eval(cp=-200),
        win_percent_drop=24.5,
        best_move_uci="d2d4",
        best_move_san="d4",
        mover_is_white=position.mover_is_white,
    )


def test_the_card_is_the_position_before_the_slip():
    card = card_from_review(target(), game_id="g", my_colour="white", depth=20)
    assert card.fen == walk(LINE)[2].fen_before
    assert card.epd == epd_of(card.fen)
    assert card.best_move_uci == "d2d4"
    assert card.my_move_san == "Nf3"
    assert card.move_label == "2.Nf3"


def test_the_last_move_is_kept_for_the_highlight():
    card = card_from_review(target(), game_id="g", my_colour="white", depth=20)
    assert card.last_move_uci == "e7e5"


def test_a_first_move_slip_has_no_last_move():
    card = card_from_review(target(0), game_id="g", my_colour="white", depth=20)
    assert card.last_move_uci is None


def test_the_epd_ignores_move_counters():
    a = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    b = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 4 9"
    assert epd_of(a) == epd_of(b)
