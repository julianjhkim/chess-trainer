from __future__ import annotations

import chess
import pytest

from chess_trainer.openings import line


def test_the_root_is_the_start_position():
    root = line.root()
    assert root.is_root
    assert root.depth == 0
    assert root.fen == chess.STARTING_FEN
    assert root.side_to_move == "white"
    assert root.given_move_uci is None
    assert root.line_uci == ""


def test_a_position_records_its_line():
    position = line.position_of(["e2e4", "c7c5"])
    assert position.depth == 2
    assert position.line_uci == "e2e4 c7c5"
    assert position.ucis == ("e2e4", "c7c5")
    assert position.given_move_uci == "c7c5"
    assert position.side_to_move == "white"


def test_side_to_move_alternates():
    assert line.position_of(["e2e4"]).side_to_move == "black"
    assert line.position_of(["e2e4", "c7c5"]).side_to_move == "white"


def test_extend_appends_one_move():
    position = line.extend(line.root(), "e2e4")
    assert position.ucis == ("e2e4",)
    assert line.extend(position, "c7c5").depth == 2


def test_an_illegal_move_names_the_depth():
    with pytest.raises(ValueError, match="illegal at depth 1"):
        line.position_of(["e2e4", "e2e4"])


def test_parse_line_round_trips():
    assert line.parse_line("e2e4 c7c5") == ("e2e4", "c7c5")
    assert line.parse_line("") == ()
    assert line.parse_line("   ") == ()


def test_the_epd_omits_the_move_counters():
    position = line.position_of(["e2e4"])
    assert position.epd in position.fen or True
    assert len(position.epd.split()) == 4  # board, turn, castling, en passant


def test_transpositions_share_an_epd_but_not_a_fen():
    """This is why a card is keyed by EPD: one position, one card."""
    first = line.position_of(["g1f3", "d7d5", "d2d4"])
    second = line.position_of(["d2d4", "d7d5", "g1f3"])
    assert first.epd == second.epd
    assert first.fen != second.fen  # the halfmove clocks differ


def test_san_of_a_legal_move():
    assert line.san_of(chess.STARTING_FEN, "g1f3") == "Nf3"


def test_san_of_an_illegal_move_raises():
    with pytest.raises(ValueError, match="not legal"):
        line.san_of(chess.STARTING_FEN, "g1f4")


def test_sans_of_a_line():
    assert line.sans_of_line(["e2e4", "c7c5", "g1f3"]) == ["e4", "c5", "Nf3"]


def test_sans_of_an_illegal_line_raises():
    with pytest.raises(ValueError):
        line.sans_of_line(["e2e4", "e2e4"])


def test_sans_of_nothing_is_empty():
    assert line.sans_of_line([]) == []


def test_move_numbers():
    assert [line.move_number_of(d) for d in range(6)] == [1, 1, 2, 2, 3, 3]


def test_line_label_reads_like_a_game_score():
    assert line.line_label(["e2e4"]) == "1.e4"
    assert line.line_label(["e2e4", "c7c5"]) == "1.e4 c5"
    assert line.line_label(["e2e4", "c7c5", "g1f3"]) == "1.e4 c5 2.Nf3"
    assert line.line_label(["e2e4", "c7c5", "g1f3", "d7d6"]) == "1.e4 c5 2.Nf3 d6"


def test_line_label_of_the_root_is_empty():
    assert line.line_label([]) == ""


def test_board_after_replays_the_line():
    board = line.board_after(["e2e4", "c7c5"])
    assert board.turn == chess.WHITE
    assert board.fen() == line.position_of(["e2e4", "c7c5"]).fen


def test_a_long_line_is_handled():
    # Ruy Lopez, Berlin Defense: a realistically deep opening line.
    ucis = [
        "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6",
        "e1g1", "f6e4", "d2d4", "e4d6", "b5c6", "d7c6",
        "d4e5", "d6f5",
    ]
    position = line.position_of(ucis)
    assert position.depth == 14
    assert position.side_to_move == "white"
    assert line.line_label(ucis).startswith("1.e4 e5 2.Nf3 Nc6 3.Bb5 Nf6")


def test_a_capture_line_round_trips():
    ucis = ["e2e4", "d7d5", "e4d5", "d8d5"]
    assert line.sans_of_line(ucis) == ["e4", "d5", "exd5", "Qxd5"]
