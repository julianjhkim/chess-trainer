from __future__ import annotations

import chess
import pytest

from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.pgn.positions import from_parsed, line_up_to, walk

SIMPLE = '[White "a"]\n[Black "b"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'


def test_walk_records_one_entry_per_move():
    positions = walk(["e2e4", "e7e5", "g1f3"])
    assert len(positions) == 3


def test_plies_are_zero_based_and_sequential():
    assert [p.ply for p in walk(["e2e4", "e7e5", "g1f3"])] == [0, 1, 2]


def test_move_numbers_follow_pgn_convention():
    positions = walk(["e2e4", "e7e5", "g1f3", "b8c6"])
    assert [p.move_number for p in positions] == [1, 1, 2, 2]


def test_movers_alternate_starting_with_white():
    positions = walk(["e2e4", "e7e5", "g1f3"])
    assert [p.mover_is_white for p in positions] == [True, False, True]
    assert [p.mover_colour for p in positions] == ["white", "black", "white"]


def test_san_is_recorded():
    assert [p.san for p in walk(["e2e4", "e7e5", "g1f3"])] == ["e4", "e5", "Nf3"]


def test_fen_before_of_the_first_move_is_the_start():
    assert walk(["e2e4"])[0].fen_before == chess.STARTING_FEN


def test_fen_after_chains_into_the_next_fen_before():
    positions = walk(["e2e4", "e7e5", "g1f3"])
    for earlier, later in zip(positions, positions[1:]):
        assert earlier.fen_after == later.fen_before


def test_move_label_formats_like_a_game_score():
    positions = walk(["e2e4", "e7e5", "g1f3"])
    assert positions[0].move_label == "1.e4"
    assert positions[1].move_label == "1...e5"
    assert positions[2].move_label == "2.Nf3"


def test_walk_from_a_custom_start():
    start = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    positions = walk(["e2e4"], start)
    assert positions[0].fen_before == start


def test_an_illegal_move_names_the_ply():
    with pytest.raises(ValueError, match="illegal at ply 1"):
        walk(["e2e4", "e2e5"])


def test_walking_nothing_gives_nothing():
    assert walk([]) == []


def test_from_parsed_matches_the_parsed_moves():
    parsed = parse_pgn(SIMPLE)
    positions = from_parsed(parsed)
    assert [p.uci for p in positions] == parsed.ucis
    assert [p.san for p in positions] == parsed.sans


def test_line_up_to_returns_the_preceding_moves():
    positions = walk(["e2e4", "e7e5", "g1f3", "b8c6"])
    assert line_up_to(positions, 2) == ["e2e4", "e7e5"]


def test_line_up_to_zero_is_empty():
    assert line_up_to(walk(["e2e4"]), 0) == []


def test_line_up_to_past_the_end_returns_everything():
    positions = walk(["e2e4", "e7e5"])
    assert line_up_to(positions, 99) == ["e2e4", "e7e5"]


def test_replaying_the_line_reaches_the_target_position():
    from chess_trainer import rules

    positions = walk(["e2e4", "e7e5", "g1f3", "b8c6"])
    target = positions[3]
    assert rules.fen_after_moves(line_up_to(positions, 3)) == target.fen_before


def test_promotion_moves_are_handled():
    # a8=Q also gives check here, so SAN carries the "+".
    positions = walk(["a7a8q"], "8/P7/8/8/8/8/8/K6k w - - 0 1")
    assert positions[0].san == "a8=Q+"
    assert positions[0].uci == "a7a8q"


def test_promotion_to_a_knight_is_distinguished():
    positions = walk(["a7a8n"], "8/P7/8/8/8/8/8/K6k w - - 0 1")
    assert positions[0].san == "a8=N"


def test_real_game_positions(chesscom_pgn):
    positions = from_parsed(parse_pgn(chesscom_pgn))
    assert len(positions) == 22
    assert positions[0].move_label == "1.e4"
    assert positions[-1].ply == 21
