from __future__ import annotations

from urllib.parse import unquote

import chess

from chess_trainer.pgn.positions import walk
from chess_trainer.review.lichess_link import analysis_url, movetext

LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]


def test_movetext_numbers_whites_moves():
    assert movetext(walk(LINE)) == "1.e4 e5 2.Nf3 Nc6 3.Bb5"


def test_movetext_for_a_game_where_black_moves_first():
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    assert movetext(walk(["e7e5", "g1f3"], fen)) == "1...e5 2.Nf3"


def test_the_url_carries_the_game_and_opens_before_the_slip():
    url = analysis_url(walk(LINE), start_fen=chess.STARTING_FEN, ply=2, my_colour="white")
    assert url.startswith("https://lichess.org/analysis/pgn/")
    assert url.endswith("?color=white#2")
    assert unquote(url.split("/pgn/")[1].split("?")[0]) == "1.e4 e5 2.Nf3 Nc6 3.Bb5"


def test_black_gets_the_board_turned_round():
    url = analysis_url(walk(LINE), start_fen=chess.STARTING_FEN, ply=3, my_colour="black")
    assert "?color=black#3" in url


def test_check_and_mate_signs_are_escaped():
    # Fool's mate ends in `Qh4#`, and a bare `#` would end the URL there.
    line = ["f2f3", "e7e5", "g2g4", "d8h4"]
    url = analysis_url(walk(line), start_fen=chess.STARTING_FEN, ply=0, my_colour="white")
    path = url.split("?")[0]
    assert "#" not in path and "+" not in path
    assert unquote(path).endswith("Qh4#")


def test_a_game_from_a_custom_position_links_to_that_position():
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    url = analysis_url(walk(["e2e4", "e8e7"], fen), start_fen=fen, ply=1, my_colour="black")
    assert url.startswith("https://lichess.org/analysis/4k3/")
    assert " " not in url
    assert url.endswith("?color=black")
    assert "_b_" in url  # the position before ply 1: Black to move


def test_the_ply_is_clamped_to_the_game():
    url = analysis_url(walk(LINE), start_fen=chess.STARTING_FEN, ply=99, my_colour="white")
    assert url.endswith(f"#{len(LINE)}")
