from __future__ import annotations

import pytest

from chess_trainer.engine import best_move
from chess_trainer.engine.eval_types import Eval
from tests.conftest import FakeEngine

FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_best_move_returns_the_engine_choice(conn):
    engine = FakeEngine(best_moves={FEN: "e2e4"})
    assert best_move.best_move(conn, engine, FEN, 20) == "e2e4"


def test_best_move_defaults_to_a_legal_move(conn, fake_engine):
    """The fake stands in for a real engine, so its answer must be playable."""
    import chess

    chosen = best_move.best_move(conn, fake_engine, FEN, 20)
    assert chess.Move.from_uci(chosen) in chess.Board(FEN).legal_moves


def test_best_move_is_cached(conn, fake_engine):
    best_move.best_move(conn, fake_engine, FEN, 20)
    best_move.best_move(conn, fake_engine, FEN, 20)
    assert fake_engine.call_count == 1


def test_is_best_move_compares_uci(conn):
    engine = FakeEngine(best_moves={FEN: "e2e4"})
    assert best_move.is_best_move(conn, engine, FEN, 20, "e2e4")
    assert not best_move.is_best_move(conn, engine, FEN, 20, "d2d4")


def test_best_among_single_candidate_skips_the_engine(conn, fake_engine):
    assert best_move.best_among(conn, fake_engine, FEN, 20, ["a2a3"]) == "a2a3"
    assert fake_engine.call_count == 0


def test_best_among_restricts_the_search(conn, fake_engine):
    chosen = best_move.best_among(conn, fake_engine, FEN, 20, ["c2c4", "d2d4"])
    assert chosen in {"c2c4", "d2d4"}
    assert fake_engine.calls[0][2] == ("c2c4", "d2d4")


def test_best_among_prefers_the_engines_pick_when_it_is_a_candidate(conn):
    engine = FakeEngine(best_moves={FEN: "d2d4"})
    assert best_move.best_among(conn, engine, FEN, 20, ["c2c4", "d2d4"]) == "d2d4"


def test_best_among_is_cached_and_order_insensitive(conn, fake_engine):
    first = best_move.best_among(conn, fake_engine, FEN, 20, ["c2c4", "g2g3"])
    second = best_move.best_among(conn, fake_engine, FEN, 20, ["g2g3", "c2c4"])
    assert first == second
    assert fake_engine.call_count == 1


def test_best_among_cache_does_not_collide_with_the_plain_entry(conn, fake_engine):
    best_move.best_move(conn, fake_engine, FEN, 20)
    best_move.best_among(conn, fake_engine, FEN, 20, ["c2c4", "g2g3"])
    assert fake_engine.call_count == 2


def test_best_among_different_candidate_sets_are_separate(conn, fake_engine):
    best_move.best_among(conn, fake_engine, FEN, 20, ["c2c4", "g2g3"])
    best_move.best_among(conn, fake_engine, FEN, 20, ["c2c4", "b2b3"])
    assert fake_engine.call_count == 2


def test_best_among_rejects_an_empty_candidate_list(conn, fake_engine):
    with pytest.raises(ValueError, match="at least one"):
        best_move.best_among(conn, fake_engine, FEN, 20, [])


def test_best_move_is_none_in_a_terminal_position(conn):
    mated = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    engine = FakeEngine(results={mated: Eval(mate=-1)}, best_moves={mated: None})
    assert best_move.best_move(conn, engine, mated, 20) is None
