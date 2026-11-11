"""Revision-card puzzles: only moves, the opponent's replies, where a line ends."""

from __future__ import annotations

import chess

from chess_trainer.engine.eval_types import Eval
from chess_trainer.inaccuracies import puzzle
from chess_trainer.openings import line as line_module
from tests.conftest import FakeEngine


def fen_of(ucis: list[str]) -> str:
    return line_module.position_of(ucis).fen


# -- only moves ----------------------------------------------------------------
def test_ten_points_of_win_percent_make_an_only_move():
    # +300 is about 75%, level is 50%: White's best is clearly the only one.
    assert puzzle.is_only_move(Eval(cp=300), Eval(cp=0), white_to_move=True)


def test_a_close_second_best_is_not_an_only_move():
    assert not puzzle.is_only_move(Eval(cp=300), Eval(cp=250), white_to_move=True)


def test_only_moves_are_judged_for_the_side_to_move():
    # Black to move: -300 is good for Black, -250 nearly as good.
    assert not puzzle.is_only_move(Eval(cp=-300), Eval(cp=-250), white_to_move=False)
    assert puzzle.is_only_move(Eval(cp=-300), Eval(cp=100), white_to_move=False)


def test_a_mate_beats_anything_that_does_not_mate():
    # Both are near 100%, but only one mates.
    assert puzzle.is_only_move(Eval(mate=3), Eval(cp=1500), white_to_move=True)
    assert not puzzle.is_only_move(Eval(mate=3), Eval(mate=5), white_to_move=True)


def test_the_only_legal_move_is_an_only_move():
    assert puzzle.is_only_move(Eval(cp=0), None, white_to_move=True)


# -- accepting moves -------------------------------------------------------------
BACK_RANK = "7k/6pp/8/8/8/8/8/RR4K1 w - - 0 1"  # Ra8# and Rb8# both mate


def test_any_mate_solves_a_mating_step():
    assert puzzle.accepts(BACK_RANK, "a1a8", "b1b8")


def test_otherwise_only_the_engines_move_solves_a_step():
    start = chess.STARTING_FEN
    assert puzzle.accepts(start, "e2e4", "e2e4")
    assert not puzzle.accepts(start, "e2e4", "d2d4")


# -- building the line -----------------------------------------------------------
def forcing_engine() -> FakeEngine:
    """1.e4! (only move) e5, 2.Nf3! (only move) Nc6, then nothing forced."""
    engine = FakeEngine()
    for ucis, best in (([], "e2e4"), (["e2e4", "e7e5"], "g1f3")):
        engine.best_moves[fen_of(ucis)] = best
        engine.results[fen_of(ucis)] = Eval(cp=300)
        engine.restricted_results[fen_of(ucis)] = Eval(cp=0)
    engine.best_moves[fen_of(["e2e4"])] = "e7e5"
    engine.best_moves[fen_of(["e2e4", "e7e5", "g1f3"])] = "b8c6"
    return engine


def test_a_forcing_line_becomes_a_puzzle(conn):
    line = puzzle.build_line(
        conn, forcing_engine(), chess.STARTING_FEN, 10, first_move="e2e4"
    )
    assert line == ("e2e4", "e7e5", "g1f3")


def test_the_line_ends_before_a_move_that_is_not_the_only_one(conn):
    engine = forcing_engine()
    engine.restricted_results[fen_of(["e2e4", "e7e5"])] = Eval(cp=280)
    line = puzzle.build_line(conn, engine, chess.STARTING_FEN, 10, first_move="e2e4")
    assert line == ("e2e4",)  # ends on my move, not on the opponent's reply


def test_the_first_move_need_not_be_the_only_one(conn):
    """It is the card's answer, judged strictly anyway; what follows is forced."""
    engine = forcing_engine()
    engine.restricted_results[chess.STARTING_FEN] = Eval(cp=290)
    line = puzzle.build_line(conn, engine, chess.STARTING_FEN, 10, first_move="e2e4")
    assert line == ("e2e4", "e7e5", "g1f3")


def test_a_mate_ends_the_line(conn):
    line = puzzle.build_line(conn, FakeEngine(), BACK_RANK, 10, first_move="a1a8")
    assert line == ("a1a8",)


def test_the_second_best_search_is_cached(conn):
    engine = forcing_engine()
    puzzle.build_line(conn, engine, chess.STARTING_FEN, 10, first_move="e2e4")
    calls = engine.call_count
    puzzle.build_line(conn, engine, chess.STARTING_FEN, 10, first_move="e2e4")
    assert engine.call_count == calls


# -- the reward -------------------------------------------------------------------
def test_the_reward_counts_material_for_the_side_to_move():
    after_e4_e5 = fen_of(["e2e4", "e7e5"])
    assert puzzle.reward(after_e4_e5, ("g1f3", "a7a6", "f3e5")) == (False, 1)
    assert puzzle.reward(after_e4_e5, ("g1f3", "a7a6", "f3e5", "d8g5", "e5f7", "g5g2")) == (False, 1)


def test_a_mate_is_a_reward_whatever_the_material():
    assert puzzle.reward(BACK_RANK, ("a1a8",)) == (True, 0)
