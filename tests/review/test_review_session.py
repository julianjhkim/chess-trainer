"""Review building and the interactive session, driven by a fake engine."""

from __future__ import annotations

from datetime import date

import pytest

from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.review.review_session import (
    ReviewSession,
    build_review,
    count_my_moves,
)
from tests.conftest import FakeEngine

PGN = '[White "me"]\n[Black "you"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n'
LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]


def parsed():
    return parse_pgn(PGN)


def fens():
    """The FEN before and after each ply of the test line."""
    from chess_trainer.pgn.positions import walk

    return walk(LINE)


def engine_with_blunder_at(ply: int, *, best_move: str = "d2d4") -> FakeEngine:
    """An engine that sees a big drop across one specific move."""
    positions = fens()
    target = positions[ply]
    results = {target.fen_before: Eval(cp=0), target.fen_after: Eval(cp=-900)}
    if not target.mover_is_white:
        results = {target.fen_before: Eval(cp=0), target.fen_after: Eval(cp=900)}
    return FakeEngine(
        results=results,
        best_moves={target.fen_before: best_move},
        default=Eval(cp=20),
    )


# -- count_my_moves ------------------------------------------------------
def test_count_my_moves_counts_only_mine():
    assert count_my_moves(parsed(), "white") == 3
    assert count_my_moves(parsed(), "black") == 3


# -- build_review --------------------------------------------------------
def test_a_clean_game_has_no_target(conn, fake_engine):
    plan = build_review(
        conn, fake_engine, parsed(), game_id="g", my_colour="white", depth=10
    )
    assert plan.target is None
    assert not plan.has_target
    assert plan.moves_assessed == 3
    assert plan.my_move_count == 3


def test_a_blunder_becomes_the_target(conn):
    engine = engine_with_blunder_at(2, best_move="d2d4")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert plan.has_target
    assert plan.target.ply == 2
    assert plan.target.my_move_san == "Nf3"
    assert plan.target.classification == "blunder"
    assert plan.target.best_move_uci == "d2d4"
    assert plan.target.best_move_san == "d4"


def test_the_target_carries_the_replay_line(conn):
    engine = engine_with_blunder_at(4, best_move="d2d4")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert plan.target.replay_ucis == ["e2e4", "e7e5", "g1f3", "b8c6"]


def test_the_replay_line_reaches_the_target_position(conn):
    from chess_trainer import rules

    engine = engine_with_blunder_at(4)
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert rules.fen_after_moves(plan.target.replay_ucis) == plan.target.fen_before


def test_a_first_move_blunder_has_an_empty_replay(conn):
    engine = engine_with_blunder_at(0, best_move="d2d4")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert plan.target.ply == 0
    assert plan.target.replay_ucis == []


def test_analysis_stops_at_the_first_inaccuracy(conn):
    """The engine must not be asked about moves after the one we stop on."""
    engine = engine_with_blunder_at(0, best_move="d2d4")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert plan.moves_assessed == 1
    # Two calls: the position before my move, and the one after it.
    assert engine.call_count == 2


def test_a_late_blunder_analyses_everything_up_to_it(conn):
    engine = engine_with_blunder_at(4, best_move="d2d4")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert plan.moves_assessed == 3


def test_only_my_moves_are_classified(conn):
    """A blunder by my opponent must not become my target.

    Consecutive plies share a position (my "after" is my opponent's "before"),
    so the evals are chosen to put the whole swing inside Black's move: level
    before it, winning for White after it, and steady from then on.
    """
    positions = fens()
    engine = FakeEngine(
        results={
            positions[0].fen_before: Eval(cp=0),   # before my 1st move
            positions[1].fen_before: Eval(cp=0),   # after it / before Black's
        },
        default=Eval(cp=900),                      # Black's move hands it over
    )
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert plan.target is None

    # The same game reviewed as Black does find it.
    as_black = build_review(
        conn, engine, parsed(), game_id="g", my_colour="black", depth=10
    )
    assert as_black.has_target
    assert as_black.target.ply == 1


def test_blacks_review_finds_blacks_blunder(conn):
    engine = engine_with_blunder_at(1, best_move="d7d5")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="black", depth=10)
    assert plan.has_target
    assert plan.target.ply == 1
    assert plan.target.my_move_san == "e5"
    assert not plan.target.mover_is_white


def test_progress_is_reported_per_move(conn, fake_engine):
    seen: list[tuple[int, int]] = []
    build_review(
        conn,
        fake_engine,
        parsed(),
        game_id="g",
        my_colour="white",
        depth=10,
        on_progress=lambda assessed, total: seen.append((assessed, total)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_progress_stops_with_the_analysis(conn):
    seen: list[tuple[int, int]] = []
    build_review(
        conn,
        engine_with_blunder_at(0, best_move="d2d4"),
        parsed(),
        game_id="g",
        my_colour="white",
        depth=10,
        on_progress=lambda assessed, total: seen.append((assessed, total)),
    )
    assert seen == [(1, 3)]


def test_a_second_review_is_served_from_the_cache(conn):
    engine = engine_with_blunder_at(4, best_move="d2d4")
    build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    calls = engine.call_count
    build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    assert engine.call_count == calls


def test_depth_and_identity_are_recorded(conn, fake_engine):
    plan = build_review(
        conn, fake_engine, parsed(), game_id="abc", my_colour="white", depth=14
    )
    assert plan.game_id == "abc"
    assert plan.depth == 14
    assert plan.my_colour == "white"


# -- ReviewSession -------------------------------------------------------
def session_with_target(conn) -> ReviewSession:
    engine = engine_with_blunder_at(2, best_move="d2d4")
    plan = build_review(conn, engine, parsed(), game_id="g", my_colour="white", depth=10)
    return ReviewSession(plan=plan)


def test_a_new_session_is_unfinished(conn):
    session = session_with_target(conn)
    assert not session.finished
    assert session.attempt_count == 0
    assert not session.solved


def test_a_correct_attempt_solves_it(conn):
    session = session_with_target(conn)
    assert session.attempt("d2d4")
    assert session.solved
    assert session.finished
    assert session.attempt_count == 1


def test_a_wrong_attempt_does_not_finish_the_review(conn):
    session = session_with_target(conn)
    assert not session.attempt("a2a3")
    assert not session.solved
    assert not session.finished


def test_retries_are_unlimited(conn):
    session = session_with_target(conn)
    for _ in range(25):
        session.attempt("a2a3")
    assert session.attempt_count == 25
    assert not session.finished
    assert session.attempt("d2d4")


def test_attempts_are_recorded_in_order(conn):
    session = session_with_target(conn)
    session.attempt("a2a3")
    session.attempt("h2h4")
    assert session.attempts == ["a2a3", "h2h4"]


def test_showing_the_answer_finishes_the_review(conn):
    session = session_with_target(conn)
    assert session.show_answer() == "d2d4"
    assert session.used_show_answer
    assert session.finished
    assert not session.solved


def test_a_session_with_no_target_is_already_finished(conn, fake_engine):
    plan = build_review(
        conn, fake_engine, parsed(), game_id="g", my_colour="white", depth=10
    )
    session = ReviewSession(plan=plan)
    assert session.finished
    assert session.target is None


def test_attempting_without_a_target_is_an_error(conn, fake_engine):
    plan = build_review(
        conn, fake_engine, parsed(), game_id="g", my_colour="white", depth=10
    )
    session = ReviewSession(plan=plan)
    with pytest.raises(ValueError, match="no position to solve"):
        session.attempt("e2e4")
    with pytest.raises(ValueError, match="no position to solve"):
        session.show_answer()


# -- summaries -----------------------------------------------------------
def test_summary_after_solving(conn):
    session = session_with_target(conn)
    session.attempt("a2a3")
    session.attempt("d2d4")
    summary = session.summary()
    assert summary.found_an_inaccuracy
    assert summary.my_move_san == "Nf3"
    assert summary.best_move_san == "d4"
    assert summary.classification == "blunder"
    assert summary.attempts == 2
    assert not summary.solved_first_try
    assert summary.eval_before == Eval(cp=0)
    assert summary.eval_after == Eval(cp=-900)


def test_summary_after_a_first_try_solve(conn):
    session = session_with_target(conn)
    session.attempt("d2d4")
    assert session.summary().solved_first_try


def test_summary_when_the_answer_was_revealed(conn):
    session = session_with_target(conn)
    session.show_answer()
    summary = session.summary()
    assert summary.used_show_answer
    assert not summary.solved_first_try


def test_summary_for_a_clean_game(conn, fake_engine):
    plan = build_review(
        conn, fake_engine, parsed(), game_id="g", my_colour="white", depth=10
    )
    summary = ReviewSession(plan=plan).summary()
    assert not summary.found_an_inaccuracy
    assert summary.best_move_san is None


# -- history rows --------------------------------------------------------
def test_history_row_carries_the_details(conn):
    session = session_with_target(conn)
    session.attempt("a2a3")
    session.attempt("d2d4")
    row = session.to_history(date(2026, 10, 30))
    assert row.game_id == "g"
    assert row.reviewed_on == date(2026, 10, 30)
    assert row.first_inaccuracy_ply == 2
    assert row.my_move_san == "Nf3"
    assert row.best_move_san == "d4"
    assert row.classification == "blunder"
    assert row.attempts == 2
    assert not row.used_show_answer
    assert row.depth == 10
    assert row.found_an_inaccuracy


def test_history_row_records_a_reveal(conn):
    session = session_with_target(conn)
    session.show_answer()
    assert session.to_history(date(2026, 10, 30)).used_show_answer


def test_history_row_for_a_clean_game_is_mostly_empty(conn, fake_engine):
    plan = build_review(
        conn, fake_engine, parsed(), game_id="g", my_colour="white", depth=10
    )
    row = ReviewSession(plan=plan).to_history(date(2026, 10, 30))
    assert row.first_inaccuracy_ply is None
    assert row.my_move_san is None
    assert not row.found_an_inaccuracy
    assert row.game_id == "g"


# -- the real game -------------------------------------------------------
def test_the_real_game_is_reviewable_with_canned_evals(conn, chesscom_pgn):
    """End to end on the committed PGN, with the engine faked."""
    from chess_trainer.pgn.positions import from_parsed

    real = parse_pgn(chesscom_pgn)
    positions = from_parsed(real)
    # Make my 4th move (ply 6) look like a blunder.
    target = positions[6]
    engine = FakeEngine(
        results={target.fen_before: Eval(cp=0), target.fen_after: Eval(cp=-900)},
        best_moves={target.fen_before: positions[6].uci},
        default=Eval(cp=15),
    )
    plan = build_review(
        conn, engine, real, game_id="real", my_colour="white", depth=10
    )
    assert plan.target.ply == 6
    assert plan.target.move_number == 4
    assert len(plan.target.replay_ucis) == 6


# -- hints ---------------------------------------------------------------
def test_a_hint_gives_the_square_the_answer_moves_from(conn):
    session = session_with_target(conn)
    assert session.hint() == "d2"
    assert session.used_hint


def test_a_hint_does_not_finish_or_count_as_an_attempt(conn):
    session = session_with_target(conn)
    session.hint()
    assert not session.finished
    assert session.attempt_count == 0


def test_no_hint_once_the_review_is_over(conn):
    session = session_with_target(conn)
    session.attempt("d2d4")
    with pytest.raises(ValueError):
        session.hint()


def test_no_hint_without_a_target(conn, fake_engine):
    plan = build_review(conn, fake_engine, parsed(), game_id="g", my_colour="white", depth=10)
    with pytest.raises(ValueError):
        ReviewSession(plan).hint()


def test_the_summary_and_history_note_a_hint(conn):
    session = session_with_target(conn)
    session.hint()
    session.attempt("d2d4")
    assert session.summary().used_hint
    assert session.to_history(date(2026, 10, 30)).used_hint


def test_without_a_hint_nothing_is_noted(conn):
    session = session_with_target(conn)
    session.attempt("d2d4")
    assert not session.summary().used_hint
    assert not session.to_history(date(2026, 10, 30)).used_hint
