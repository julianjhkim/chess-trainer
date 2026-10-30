"""Cached analysis, exercised with a fake engine (no Stockfish process)."""

from __future__ import annotations

from chess_trainer.db import analysis_repo
from chess_trainer.engine import analysis
from chess_trainer.engine.eval_types import Eval

FEN_A = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FEN_B = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def test_first_call_hits_the_engine(conn, fake_engine):
    result = analysis.analyse(conn, fake_engine, FEN_A, 20)
    assert fake_engine.call_count == 1
    assert result.evaluation == Eval(cp=20)
    assert result.depth == 20


def test_result_is_written_to_the_cache(conn, fake_engine):
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    assert analysis_repo.get(conn, FEN_A, 20) is not None


def test_second_call_is_served_from_the_cache(conn, fake_engine):
    first = analysis.analyse(conn, fake_engine, FEN_A, 20)
    second = analysis.analyse(conn, fake_engine, FEN_A, 20)
    assert fake_engine.call_count == 1
    assert first == second


def test_different_depth_is_a_separate_entry(conn, fake_engine):
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    analysis.analyse(conn, fake_engine, FEN_A, 10)
    assert fake_engine.call_count == 2


def test_use_cache_false_forces_a_fresh_search(conn, fake_engine):
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    analysis.analyse(conn, fake_engine, FEN_A, 20, use_cache=False)
    assert fake_engine.call_count == 2


def test_cached_only_never_calls_the_engine(conn, fake_engine):
    assert analysis.cached_only(conn, FEN_A, 20) is None
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    assert analysis.cached_only(conn, FEN_A, 20) is not None
    assert fake_engine.call_count == 1


def test_analyse_many_returns_results_in_order(conn, fake_engine):
    results = list(analysis.analyse_many(conn, fake_engine, [FEN_A, FEN_B], 20))
    assert [r.fen for r in results] == [FEN_A, FEN_B]


def test_analyse_many_is_lazy(conn, fake_engine):
    """The review stops at the first inaccuracy, so nothing may be analysed early."""
    generator = analysis.analyse_many(conn, fake_engine, [FEN_A, FEN_B], 20)
    assert fake_engine.call_count == 0
    next(generator)
    assert fake_engine.call_count == 1


def test_analyse_many_reuses_cached_entries(conn, fake_engine):
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    list(analysis.analyse_many(conn, fake_engine, [FEN_A, FEN_B], 20))
    assert fake_engine.call_count == 2  # FEN_A came from the cache


def test_asking_for_a_line_re_searches_a_result_cached_without_one(conn, fake_engine):
    from chess_trainer.engine.stockfish import EngineAnalysis

    analysis_repo.put(
        conn, EngineAnalysis(fen=FEN_A, depth=20, evaluation=Eval(cp=5), best_move="e2e4")
    )
    fake_engine.pvs[FEN_A] = ("e2e4", "e7e5")
    result = analysis.analyse(conn, fake_engine, FEN_A, 20, need_line=True)
    assert fake_engine.call_count == 1
    assert result.pv == ("e2e4", "e7e5")
    # ...and the fresh line replaces the old entry, so it is searched only once.
    analysis.analyse(conn, fake_engine, FEN_A, 20, need_line=True)
    assert fake_engine.call_count == 1


def test_a_cached_line_is_used_as_is(conn, fake_engine):
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    analysis.analyse(conn, fake_engine, FEN_A, 20, need_line=True)
    assert fake_engine.call_count == 1


def test_without_asking_for_a_line_an_old_entry_is_fine(conn, fake_engine):
    from chess_trainer.engine.stockfish import EngineAnalysis

    analysis_repo.put(
        conn, EngineAnalysis(fen=FEN_A, depth=20, evaluation=Eval(cp=5), best_move="e2e4")
    )
    analysis.analyse(conn, fake_engine, FEN_A, 20)
    assert fake_engine.call_count == 0
