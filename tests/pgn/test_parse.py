from __future__ import annotations

import chess
import pytest

from chess_trainer.pgn import parse
from chess_trainer.pgn.parse import PgnParseError, PlayerNotInGame, end_time_of, parse_pgn

SIMPLE = '''[Event "Test"]
[White "test-player"]
[Black "rival"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
'''

WITH_CLOCKS = '''[Event "Live Chess"]
[White "test-player"]
[Black "rival"]
[UTCDate "2025.01.15"]
[UTCTime "12:00:00"]
[EndDate "2025.01.15"]
[EndTime "12:03:34"]
[Result "0-1"]

1. e4 {[%clk 0:09:58.9]} 1... e5 {[%clk 0:09:59]} 2. Nf3 {[%clk 0:09:58.4]} 0-1
'''

WITH_VARIATION = '''[White "a"]
[Black "b"]

1. e4 (1. d4 d5) e5 2. Nf3 *
'''

FROM_FEN = '''[White "a"]
[Black "b"]
[SetUp "1"]
[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]

1. e4 Kd7 *
'''


def test_simple_pgn_is_parsed():
    parsed = parse_pgn(SIMPLE)
    assert parsed.sans == ["e4", "e5", "Nf3", "Nc6"]
    assert parsed.ucis == ["e2e4", "e7e5", "g1f3", "b8c6"]
    assert parsed.move_count == 4


def test_headers_are_kept():
    parsed = parse_pgn(SIMPLE)
    assert parsed.white == "test-player"
    assert parsed.black == "rival"
    assert parsed.result == "1-0"


def test_clock_comments_are_tolerated():
    parsed = parse_pgn(WITH_CLOCKS)
    assert parsed.sans == ["e4", "e5", "Nf3"]


def test_only_the_main_line_is_kept():
    parsed = parse_pgn(WITH_VARIATION)
    assert parsed.sans == ["e4", "e5", "Nf3"]


def test_a_set_up_position_is_honoured():
    parsed = parse_pgn(FROM_FEN)
    assert parsed.start_fen.startswith("4k3")
    assert parsed.sans == ["e4", "Kd7"]


def test_default_start_is_the_standard_position():
    assert parse_pgn(SIMPLE).start_fen == chess.STARTING_FEN


def test_empty_input_is_rejected():
    with pytest.raises(PgnParseError, match="No PGN"):
        parse_pgn("")
    with pytest.raises(PgnParseError, match="No PGN"):
        parse_pgn("   \n  ")


def test_nonsense_is_rejected():
    with pytest.raises(PgnParseError):
        parse_pgn("this is not a pgn at all")


def test_a_pgn_with_no_moves_is_rejected():
    with pytest.raises(PgnParseError, match="no moves"):
        parse_pgn('[White "a"]\n[Black "b"]\n[Result "*"]\n\n*\n')


def test_an_illegal_move_is_reported():
    """python-chess truncates at a bad move; we must refuse, not review a stub."""
    bad = '[White "a"]\n[Black "b"]\n\n1. e4 e5 2. Qh8 *\n'
    with pytest.raises(PgnParseError, match="could not be read in full"):
        parse_pgn(bad)


def test_a_truncating_pgn_does_not_silently_shorten_the_game():
    bad = '[White "a"]\n[Black "b"]\n\n1. e4 zzz 2. Nf3 *\n'
    with pytest.raises(PgnParseError, match="could not be read in full"):
        parse_pgn(bad)


def test_an_illegal_castle_is_reported():
    with pytest.raises(PgnParseError, match="could not be read in full"):
        parse_pgn('[White "a"]\n[Black "b"]\n\n1. O-O *\n')


def test_an_invalid_fen_header_is_reported():
    bad = '[White "a"]\n[Black "b"]\n[FEN "garbage"]\n\n1. e4 *\n'
    with pytest.raises(PgnParseError) as caught:
        parse_pgn(bad)
    assert "fen" in str(caught.value).lower()


def test_colour_of_finds_each_side():
    parsed = parse_pgn(SIMPLE)
    assert parsed.colour_of("test-player") == "white"
    assert parsed.colour_of("rival") == "black"


def test_colour_of_ignores_case():
    assert parse_pgn(SIMPLE).colour_of("Test-Player") == "white"


def test_colour_of_rejects_a_stranger():
    with pytest.raises(PlayerNotInGame, match="did not play"):
        parse_pgn(SIMPLE).colour_of("magnus")


def test_played_by():
    parsed = parse_pgn(SIMPLE)
    assert parsed.played_by("rival")
    assert not parsed.played_by("someone else")


def test_end_time_prefers_the_end_headers():
    # 2026-10-28 12:03:34 UTC
    assert end_time_of(parse_pgn(WITH_CLOCKS)) == 1736942614


def test_end_time_falls_back_to_the_date_header():
    pgn = '[White "a"]\n[Black "b"]\n[Date "2026.01.02"]\n\n1. e4 *\n'
    stamp = end_time_of(parse_pgn(pgn))
    assert stamp is not None


def test_end_time_is_none_without_dates():
    pgn = '[White "a"]\n[Black "b"]\n\n1. e4 *\n'
    assert end_time_of(parse_pgn(pgn)) is None


def test_end_time_ignores_unknown_dates():
    pgn = '[White "a"]\n[Black "b"]\n[Date "????.??.??"]\n\n1. e4 *\n'
    assert end_time_of(parse_pgn(pgn)) is None


def test_url_comes_from_the_link_header():
    pgn = '[White "a"]\n[Black "b"]\n[Link "https://chess.com/game/1"]\n\n1. e4 *\n'
    assert parse_pgn(pgn).url == "https://chess.com/game/1"


def test_real_chesscom_pgn_round_trips(chesscom_pgn):
    parsed = parse_pgn(chesscom_pgn)
    assert parsed.move_count == 22
    assert parsed.colour_of("test-player") == "white"
    assert end_time_of(parsed) == 1736942614
