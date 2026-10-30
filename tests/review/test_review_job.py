"""The background review job: progress, completion and failure."""

from __future__ import annotations

import time

from chess_trainer.db.games_repo import StoredGame
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.review.review_job import ReviewStatus, create_job
from chess_trainer.session.steps import Step
from tests.conftest import FakeEngine

PGN = '[White "me"]\n[Black "you"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n'


def stored() -> StoredGame:
    return StoredGame(id="game-1", pgn=PGN, my_color="white")


def job():
    return create_job(stored(), parse_pgn(PGN), my_colour="white", depth=10)


def test_a_new_job_is_analysing():
    created = job()
    assert created.status is ReviewStatus.ANALYSING
    assert not created.is_ready
    assert created.session is None


def test_total_moves_is_known_before_analysing():
    assert job().total_moves == 3


def test_progress_starts_at_zero():
    created = job()
    assert created.assessed == 0
    assert created.progress_fraction == 0.0


def test_running_to_completion_makes_it_ready(conn, fake_engine):
    created = job()
    created.start(conn, fake_engine)
    assert created.wait(timeout=10)
    assert created.status is ReviewStatus.READY
    assert created.is_ready
    assert created.session is not None


def test_progress_reaches_the_total(conn, fake_engine):
    created = job()
    created.start(conn, fake_engine)
    created.wait(timeout=10)
    assert created.assessed == 3
    assert created.progress_fraction == 1.0


def test_a_clean_game_yields_a_session_with_no_target(conn, fake_engine):
    created = job()
    created.start(conn, fake_engine)
    created.wait(timeout=10)
    assert created.session.target is None
    assert created.session.finished


def test_a_blunder_yields_a_solvable_session(conn):
    from chess_trainer.pgn.positions import from_parsed

    parsed = parse_pgn(PGN)
    target = from_parsed(parsed)[2]
    engine = FakeEngine(
        results={target.fen_before: Eval(cp=0), target.fen_after: Eval(cp=-900)},
        best_moves={target.fen_before: "d2d4"},
    )
    created = job()
    created.start(conn, engine)
    created.wait(timeout=10)
    assert created.session.target.best_move_uci == "d2d4"
    assert not created.session.finished


def test_an_engine_failure_is_captured_not_raised(conn):
    class BrokenEngine:
        def analyse(self, fen, depth, *, root_moves=None):
            raise RuntimeError("engine died")

    created = job()
    created.start(conn, BrokenEngine())
    assert created.wait(timeout=10)
    assert created.status is ReviewStatus.FAILED
    assert "engine died" in created.error
    assert not created.is_ready


def test_an_illegal_line_is_rejected_when_the_job_is_created():
    """Counting my moves walks the line, so a bad line fails fast and loudly.

    parse_pgn already refuses illegal lines, so this can only come from a bug;
    the review router turns it into a 422 rather than a 500.
    """
    import pytest

    parsed = parse_pgn(PGN)
    broken = type(parsed)(
        ucis=["e2e4", "e2e4"], sans=["e4", "e4"], headers=parsed.headers
    )
    with pytest.raises(ValueError, match="illegal at ply 1"):
        create_job(stored(), broken, my_colour="white", depth=10)


def test_progress_fraction_of_an_empty_game_is_complete():
    parsed = parse_pgn(PGN)
    empty = type(parsed)(ucis=[], sans=[], headers=parsed.headers)
    created = create_job(stored(), empty, my_colour="white", depth=10)
    assert created.total_moves == 0
    assert created.progress_fraction == 1.0


def test_wait_on_a_job_never_started_returns_immediately():
    assert not job().wait(timeout=0.1)


# -- cancellation / shutdown safety -------------------------------------
class SlowEngine:
    """An engine whose searches take long enough to shut down underneath."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.calls = 0

    def analyse(self, fen, depth, *, root_moves=None):
        import chess

        from chess_trainer.engine.eval_types import Eval
        from chess_trainer.engine.stockfish import EngineAnalysis

        self.calls += 1
        time.sleep(self.delay)
        board = chess.Board(fen)
        best = next((m.uci() for m in board.legal_moves), None)
        return EngineAnalysis(
            fen=fen, depth=depth, evaluation=Eval(cp=10), best_move=best
        )


def test_cancelling_stops_the_analysis(conn):
    created = job()
    created.start(conn, SlowEngine(delay=0.05))
    created.cancel()
    assert created.wait(timeout=10)
    assert created.status is ReviewStatus.CANCELLED
    assert created.session is None


def test_a_cancelled_job_is_not_ready(conn):
    created = job()
    created.start(conn, SlowEngine())
    created.cancel()
    created.wait(timeout=10)
    assert not created.is_ready


def test_is_running_reflects_the_thread(conn, fake_engine):
    created = job()
    assert not created.is_running
    created.start(conn, fake_engine)
    created.wait(timeout=10)
    assert not created.is_running


def test_cancelling_a_finished_job_is_harmless(conn, fake_engine):
    created = job()
    created.start(conn, fake_engine)
    created.wait(timeout=10)
    created.cancel()
    assert created.status is ReviewStatus.READY


def test_shutdown_during_analysis_does_not_use_a_closed_connection(config):
    """Regression: closing the database under a running review segfaulted.

    The review thread reads the connection; AppState.shutdown must cancel and
    join the thread before closing it.
    """
    from chess_trainer.api.deps import AppState

    state = AppState(config)
    created = job()
    state.reviews[Step.REVIEW_LAST_GAME] = created
    created.start(state.conn, SlowEngine(delay=0.05))

    state.shutdown()

    assert not created.is_running
    assert created.status in {ReviewStatus.CANCELLED, ReviewStatus.READY}


def test_shutdown_closes_the_connection_when_nothing_is_running(config):
    import sqlite3

    import pytest

    from chess_trainer.api.deps import AppState

    state = AppState(config)
    conn = state.conn
    state.shutdown()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
