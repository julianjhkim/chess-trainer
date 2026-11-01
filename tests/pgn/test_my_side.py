from __future__ import annotations

from chess_trainer.pgn.my_side import normalise, side_of
from chess_trainer.pgn.parse import parse_pgn

MOVES = "\n\n1. e4 e5 *\n"


def game(white: str, black: str):
    return parse_pgn(f'[White "{white}"]\n[Black "{black}"]{MOVES}')


def test_any_of_my_names_finds_my_side():
    names = ["old-account", "new-account"]
    assert side_of(game("new-account", "rival"), names) == "white"
    assert side_of(game("rival", "old-account"), names) == "black"


def test_names_match_without_regard_to_case():
    assert side_of(game("rival", "New-Account"), ["new-account"]) == "black"


def test_a_game_without_me_has_no_side():
    assert side_of(game("someone", "rival"), ["new-account"]) is None
    assert side_of(game("someone", "rival"), []) is None


def test_a_game_between_two_of_my_names_is_ambiguous():
    assert side_of(game("old-account", "new-account"), ["old-account", "new-account"]) is None


def test_normalise_trims_drops_blanks_and_repeats():
    assert normalise(["  a-name ", "", "A-NAME", "other", "   "]) == ["a-name", "other"]
