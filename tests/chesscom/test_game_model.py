from __future__ import annotations

import pytest

from chess_trainer.chesscom import game_model
from chess_trainer.chesscom.game_model import NotMyGame, parse_game, parse_games

PGN = '[White "test-player"]\n[Black "rival"]\n\n1. e4 e5 1-0\n'


def payload(**overrides):
    base = {
        "url": "https://www.chess.com/game/live/100000000001",
        "uuid": "00000000-0000-4000-8000-000000000001",
        "pgn": PGN,
        "rules": "chess",
        "time_class": "rapid",
        "end_time": 1736942614,
        "white": {"username": "test-player", "result": "resigned", "rating": 1500},
        "black": {"username": "rival", "result": "win", "rating": 1480},
    }
    base.update(overrides)
    return base


def test_parse_game_extracts_the_essentials():
    game = parse_game(payload())
    assert game.id == "00000000-0000-4000-8000-000000000001"
    assert game.white_username == "test-player"
    assert game.black_username == "rival"
    assert game.white_result == "resigned"
    assert game.black_result == "win"
    assert game.time_class == "rapid"
    assert game.end_time == 1736942614


def test_id_prefers_the_uuid():
    assert parse_game(payload()).id.startswith("00000000")


def test_id_falls_back_to_the_url_segment():
    game = parse_game(payload(uuid=None))
    assert game.id == "100000000001"


def test_id_falls_back_to_a_pgn_digest():
    game = parse_game(payload(uuid=None, url=None))
    assert game.id.startswith("pgn-")


def test_pgn_digest_is_stable():
    first = game_model.game_id({"pgn": PGN})
    second = game_model.game_id({"pgn": PGN})
    assert first == second


def test_pgn_digest_differs_for_different_games():
    assert game_model.game_id({"pgn": PGN}) != game_model.game_id({"pgn": PGN + "x"})


def test_missing_pgn_is_rejected():
    with pytest.raises(ValueError, match="no PGN"):
        parse_game(payload(pgn=None))


def test_blank_pgn_is_rejected():
    with pytest.raises(ValueError, match="no PGN"):
        parse_game(payload(pgn="   "))


def test_colour_of_finds_white():
    assert parse_game(payload()).colour_of("test-player") == "white"


def test_colour_of_finds_black():
    assert parse_game(payload()).colour_of("rival") == "black"


def test_colour_of_ignores_case_and_whitespace():
    assert parse_game(payload()).colour_of("  test-player ") == "white"


def test_colour_of_rejects_a_stranger():
    with pytest.raises(NotMyGame, match="did not play"):
        parse_game(payload()).colour_of("magnus")


def test_played_by_is_a_boolean_form_of_colour_of():
    game = parse_game(payload())
    assert game.played_by("rival")
    assert not game.played_by("magnus")


def test_standard_chess_is_reviewable():
    assert parse_game(payload()).is_standard


def test_variants_are_not_reviewable():
    assert not parse_game(payload(rules="chess960")).is_standard
    assert not parse_game(payload(rules="bughouse")).is_standard


def test_missing_rules_is_assumed_standard():
    assert parse_game(payload(rules=None)).is_standard


def test_malformed_player_objects_do_not_crash():
    game = parse_game(payload(white="not a dict", black=None))
    assert game.white_username is None
    assert game.black_username is None


def test_non_numeric_end_time_becomes_none():
    assert parse_game(payload(end_time="yesterday")).end_time is None


def test_parse_games_skips_entries_without_a_pgn():
    games = parse_games([payload(), payload(uuid="other", pgn=None)])
    assert len(games) == 1


def test_parse_games_of_nothing_is_empty():
    assert parse_games([]) == []
