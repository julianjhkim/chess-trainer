from __future__ import annotations

from chess_trainer.pgn.positions import walk
from chess_trainer.review.my_moves import is_mine, mine, opponents

LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]


def test_white_gets_the_odd_plies():
    assert [p.ply for p in mine(walk(LINE), "white")] == [0, 2, 4]


def test_black_gets_the_even_plies():
    assert [p.ply for p in mine(walk(LINE), "black")] == [1, 3]


def test_mine_and_opponents_partition_the_game():
    positions = walk(LINE)
    assert len(mine(positions, "white")) + len(opponents(positions, "white")) == len(positions)


def test_opponents_is_the_complement():
    positions = walk(LINE)
    assert opponents(positions, "white") == mine(positions, "black")


def test_order_is_preserved():
    plies = [p.ply for p in mine(walk(LINE), "white")]
    assert plies == sorted(plies)


def test_is_mine_for_a_single_position():
    positions = walk(LINE)
    assert is_mine(positions[0], "white")
    assert not is_mine(positions[0], "black")


def test_empty_game_gives_no_moves():
    assert mine([], "white") == []


def test_real_game(chesscom_pgn):
    from chess_trainer.pgn.parse import parse_pgn
    from chess_trainer.pgn.positions import from_parsed

    positions = from_parsed(parse_pgn(chesscom_pgn))
    white = mine(positions, "white")
    assert len(white) == 11
    assert all(p.mover_is_white for p in white)
