from __future__ import annotations

import chess

from chess_trainer.engine.eval_types import Eval
from chess_trainer.review import explain

START = chess.STARTING_FEN
#: 1.e4 e5 2.Bc4 Nc6 3.Qh5, Black to move: 3...Nf6?? walks into Qxf7#.
SCHOLAR = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
#: White to move, and Black's queen on d5 is simply hanging.
HANGING_QUEEN = "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1"


# -- reading lines -----------------------------------------------------------
def test_a_line_stops_at_the_first_illegal_move():
    moves = explain.legal_prefix(START, ["e2e4", "e7e5", "e4e5", "g1f3"])
    assert [m.uci() for m in moves] == ["e2e4", "e7e5"]


def test_a_quiet_line_is_cut_at_the_limit():
    line = ["g1f3", "g8f6", "f3g1", "f6g8"]
    assert explain.trim(START, line, max_plies=2) == ["g1f3", "g8f6"]


def test_a_line_is_not_cut_in_the_middle_of_a_trade():
    line = ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5"]
    # The cut falls after 2.exd5, so the recapture and the reply to it stay.
    assert explain.trim(START, line, max_plies=3) == line[:5]


def test_a_forcing_line_still_ends():
    line = ["g1f3", "g8f6", "f3g1", "f6g8"] * 5
    assert len(explain.trim(START, line, max_plies=2)) == 2


def test_moves_are_labelled_as_in_a_score():
    moves = explain.line_moves(START, ["e2e4", "e7e5", "g1f3"])
    assert [m.label for m in moves] == ["1.e4", "1...e5", "2.Nf3"]
    assert [m.mover_is_white for m in moves] == [True, False, True]


def test_each_move_carries_the_position_after_it():
    moves = explain.line_moves(START, ["e2e4"])
    assert moves[0].fen_after.startswith("rnbqkbnr/pppppppp/8/8/4P3/")


def test_captures_are_split_by_side():
    won, lost = explain.captures(
        START, ["e2e4", "d7d5", "e4d5", "d8d5"], me_white=True
    )
    assert won == [chess.PAWN]
    assert lost == [chess.PAWN]


# -- words -------------------------------------------------------------------
def test_move_facts_name_the_captured_piece():
    assert explain.move_facts(HANGING_QUEEN, "d1d5") == ["captures the queen on d5"]


def test_move_facts_see_checkmate():
    facts = explain.move_facts(
        "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "h5f7"
    )
    assert facts == ["captures the pawn on f7", "is checkmate"]


def test_a_quiet_move_has_no_facts():
    assert explain.move_facts(START, "g1f3") == []


def test_pieces_are_grouped_and_ordered_by_value():
    phrase = explain.pieces_phrase([chess.PAWN, chess.KNIGHT, chess.PAWN])
    assert phrase == "a knight and two pawns"


def test_material_note_for_a_clean_win():
    assert explain.material_note([chess.QUEEN], []) == "Over this line you win a queen."


def test_material_note_for_an_even_trade():
    note = explain.material_note([chess.KNIGHT], [chess.BISHOP])
    assert note.endswith("— an even trade.")


def test_material_note_gives_the_net():
    note = explain.material_note([chess.ROOK], [chess.KNIGHT])
    assert "net +2" in note


def test_no_captures_means_no_material_note():
    assert explain.material_note([], []) is None


# -- the two lines -----------------------------------------------------------
def test_the_best_line_explains_winning_a_hanging_queen():
    line = explain.explain_best(HANGING_QUEEN, "d1d5", ["e8e7"], Eval(cp=900))
    assert [m.san for m in line.moves] == ["Qxd5", "Ke7"]
    assert "Qxd5 captures the queen on d5." in line.notes
    assert "Over this line you win a queen." in line.notes


def test_the_best_line_reports_the_evaluation():
    line = explain.explain_best(SCHOLAR, "g7g6", ["h5f3", "g8f6"], Eval(cp=-30))
    assert any(note.startswith("After it the engine rates the position") for note in line.notes)


def test_the_best_line_reports_a_forced_mate_for_me():
    line = explain.explain_best(HANGING_QUEEN, "d1d5", ["e8e7"], Eval(mate=5))
    assert "It forces mate in 5." in line.notes


def test_my_line_shows_the_punishing_reply():
    line = explain.explain_mine(
        SCHOLAR,
        "g8f6",
        ["h5f7"],
        eval_before=Eval(cp=-30),
        eval_after=Eval(mate=1),
        win_percent_drop=100.0,
    )
    assert [m.label for m in line.moves] == ["3...Nf6", "4.Qxf7#"]
    assert (
        "The engine answers 4.Qxf7#, which captures your pawn on f7 and is checkmate."
        in line.notes
    )
    assert any(note.startswith("It allows mate in 1") for note in line.notes)
    assert "Over this line you lose a pawn." in line.notes


def test_my_line_reports_the_cost_when_there_is_no_mate():
    line = explain.explain_mine(
        START,
        "f2f3",
        ["e7e5"],
        eval_before=Eval(cp=20),
        eval_after=Eval(cp=-60),
        win_percent_drop=7.4,
    )
    assert any("costs 7.4% of your winning chances" in note for note in line.notes)
    assert "The engine answers 1...e5." in line.notes


def test_explain_returns_both_lines():
    result = explain.explain(
        HANGING_QUEEN,
        best_uci="d1d5",
        best_reply_pv=["e8e7"],
        best_eval=Eval(cp=900),
        my_uci="d1d2",
        my_reply_pv=["d5d2"],
        eval_before=Eval(cp=900),
        eval_after=Eval(cp=-900),
        win_percent_drop=95.0,
    )
    assert result.best.moves[0].san == "Qxd5"
    assert result.mine.moves[0].san == "Qd2"
    assert "Over this line you lose a queen." in result.mine.notes


def test_an_engine_line_that_goes_illegal_is_cut_there():
    line = explain.explain_best(HANGING_QUEEN, "d1d5", ["e8e7", "a1a2"], Eval(cp=900))
    assert len(line.moves) == 2
