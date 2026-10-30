"""Tests that start the real Stockfish process.

These skip automatically when the binary is not installed, so the suite still
passes on a machine without it.
"""

from __future__ import annotations

import pytest

from chess_trainer.engine.eval_format import format_eval
from chess_trainer.engine.stockfish import (
    EngineNotAvailable,
    StockfishEngine,
    _score_to_eval,
    _terminal_eval,
)

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
MATE_IN_ONE = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
WHITE_MATED = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
STALEMATE = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


def test_missing_binary_is_reported_clearly(tmp_path):
    engine = StockfishEngine(tmp_path / "no-such-stockfish")
    with pytest.raises(EngineNotAvailable, match="not found"):
        engine.start()


def test_is_running_reflects_lifecycle(real_engine):
    assert real_engine.is_running
    real_engine.close()
    assert not real_engine.is_running


def test_context_manager_starts_and_stops(tmp_path):
    from tests.conftest import STOCKFISH_PATH

    if not STOCKFISH_PATH.exists():
        pytest.skip("Stockfish not installed")
    with StockfishEngine(STOCKFISH_PATH) as engine:
        assert engine.is_running
    assert not engine.is_running


def test_start_is_idempotent(real_engine):
    real_engine.start()
    assert real_engine.is_running


def test_start_position_is_roughly_equal(real_engine):
    result = real_engine.analyse(START, 10)
    assert result.evaluation.cp is not None
    assert abs(result.evaluation.cp) < 100
    assert result.best_move is not None
    assert len(result.best_move) == 4


def test_depth_and_fen_are_echoed_back(real_engine):
    result = real_engine.analyse(START, 8)
    assert (result.fen, result.depth) == (START, 8)


def test_mate_is_found_and_formatted(real_engine):
    result = real_engine.analyse(MATE_IN_ONE, 10)
    assert result.evaluation.is_mate
    assert result.evaluation.mate == 1
    assert format_eval(result.evaluation) == "M1"
    assert result.best_move == "a1a8"


def test_terminal_position_needs_no_search(real_engine):
    result = real_engine.analyse(WHITE_MATED, 10)
    assert result.best_move is None
    assert result.evaluation.mate == -1


def test_stalemate_is_level(real_engine):
    result = real_engine.analyse(STALEMATE, 10)
    assert result.evaluation.cp == 0
    assert result.best_move is None


def test_root_moves_restricts_the_choice(real_engine):
    result = real_engine.analyse(START, 10, root_moves=["a2a3", "h2h3"])
    assert result.best_move in {"a2a3", "h2h3"}


def test_scores_are_from_whites_perspective(real_engine):
    """A position where Black is winning must score negative, whoever is to move."""
    black_up = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN1 w Qkq - 0 1"  # White lacks a rook
    assert real_engine.analyse(black_up, 8).evaluation.cp < 0


def test_terminal_eval_helper_handles_draws():
    import chess

    assert _terminal_eval(chess.Board(STALEMATE)).cp == 0


def test_score_to_eval_handles_mate_already_on_the_board():
    import chess
    import chess.engine

    score = chess.engine.PovScore(chess.engine.Mate(0), chess.BLACK)
    # Mate-in-0 against the side to move: never represented as mate=0.
    assert _score_to_eval(score).mate != 0


def test_the_line_starts_with_the_best_move(real_engine):
    result = real_engine.analyse(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 10
    )
    assert len(result.pv) > 1
    assert result.pv[0] == result.best_move
