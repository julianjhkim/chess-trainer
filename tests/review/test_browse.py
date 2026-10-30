from __future__ import annotations

from chess_trainer.pgn.positions import walk
from chess_trainer.review.browse import browsable_moves

LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]


def test_an_open_drill_shows_only_the_moves_before_the_target():
    moves = browsable_moves(walk(LINE), target_ply=2, finished=False)
    assert [m.uci for m in moves] == ["e2e4", "e7e5"]


def test_the_move_being_drilled_is_not_shown():
    moves = browsable_moves(walk(LINE), target_ply=2, finished=False)
    assert "g1f3" not in [m.uci for m in moves]


def test_a_target_on_the_first_move_shows_nothing():
    assert browsable_moves(walk(LINE), target_ply=0, finished=False) == []


def test_a_finished_review_shows_the_whole_game():
    moves = browsable_moves(walk(LINE), target_ply=2, finished=True)
    assert [m.uci for m in moves] == LINE


def test_a_game_without_an_inaccuracy_shows_the_whole_game():
    moves = browsable_moves(walk(LINE), target_ply=None, finished=True)
    assert [m.uci for m in moves] == LINE


def test_no_target_shows_everything_even_if_not_finished():
    moves = browsable_moves(walk(LINE), target_ply=None, finished=False)
    assert len(moves) == len(LINE)


def test_the_input_list_is_not_modified():
    positions = walk(LINE)
    browsable_moves(positions, target_ply=None, finished=True).clear()
    assert len(positions) == len(LINE)
