from __future__ import annotations

from chess_trainer.db import analysis_repo
from chess_trainer.engine.eval_types import Eval
from chess_trainer.engine.stockfish import EngineAnalysis

FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def analysis(cp: int | None = 25, mate: int | None = None, depth: int = 20):
    return EngineAnalysis(
        fen=FEN, depth=depth, evaluation=Eval(cp=cp, mate=mate), best_move="e2e4"
    )


def test_get_missing_returns_none(conn):
    assert analysis_repo.get(conn, FEN, 20) is None


def test_put_then_get_round_trips_a_centipawn_score(conn):
    analysis_repo.put(conn, analysis())
    stored = analysis_repo.get(conn, FEN, 20)
    assert stored.evaluation == Eval(cp=25)
    assert stored.best_move == "e2e4"
    assert stored.depth == 20


def test_mate_scores_survive_the_round_trip(conn):
    analysis_repo.put(conn, analysis(cp=None, mate=-3))
    assert analysis_repo.get(conn, FEN, 20).evaluation == Eval(mate=-3)


def test_depth_is_part_of_the_key(conn):
    analysis_repo.put(conn, analysis(cp=25, depth=20))
    analysis_repo.put(conn, analysis(cp=40, depth=10))
    assert analysis_repo.get(conn, FEN, 20).evaluation.cp == 25
    assert analysis_repo.get(conn, FEN, 10).evaluation.cp == 40
    assert analysis_repo.count(conn) == 2


def test_putting_the_same_key_updates_in_place(conn):
    analysis_repo.put(conn, analysis(cp=25))
    analysis_repo.put(conn, analysis(cp=99))
    assert analysis_repo.count(conn) == 1
    assert analysis_repo.get(conn, FEN, 20).evaluation.cp == 99


def test_count_starts_at_zero(conn):
    assert analysis_repo.count(conn) == 0
