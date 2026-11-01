from __future__ import annotations

import pytest

from chess_trainer.inaccuracies.slip import SlipNotFound, card_for, epd_of, find_slip, moves_before
from chess_trainer.pgn.positions import walk

LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]


def test_white_move_two_is_the_third_ply():
    slip = find_slip(walk(LINE), move_number=2, my_colour="white")
    assert (slip.ply, slip.san, slip.move_label) == (2, "Nf3", "2.Nf3")


def test_black_move_two_is_the_fourth_ply():
    slip = find_slip(walk(LINE), move_number=2, my_colour="black")
    assert (slip.ply, slip.san, slip.move_label) == (3, "Nc6", "2...Nc6")


def test_a_missing_move_says_which_moves_there_are():
    with pytest.raises(SlipNotFound, match="Black has no move 9 in this game: your moves run from 1 to 3"):
        find_slip(walk(LINE), move_number=9, my_colour="black")


def test_moves_before_stop_short_of_the_slip():
    positions = walk(LINE)
    slip = find_slip(positions, move_number=3, my_colour="white")
    assert [p.san for p in moves_before(positions, slip)] == ["e4", "e5", "Nf3", "Nc6"]


def test_the_card_is_the_position_before_the_slip():
    positions = walk(LINE)
    slip = find_slip(positions, move_number=2, my_colour="white")
    card = card_for(
        slip, game_id="g", my_colour="white", best_move_uci="d2d4",
        classification="mistake", win_percent_drop=21.0, depth=20, previous=positions[1],
    )
    assert card.fen == slip.fen_before and card.epd == epd_of(slip.fen_before)
    assert (card.best_move_san, card.my_move_san, card.last_move_uci) == ("d4", "Nf3", "e7e5")
