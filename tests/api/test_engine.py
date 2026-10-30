from __future__ import annotations

from chess_trainer.engine.eval_types import Eval

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_eval_returns_a_formatted_evaluation(client, fake_engine_for_api):
    fake_engine_for_api.best_moves[START] = "e2e4"
    payload = client.post("/api/engine/eval", json={"fen": START}).json()
    assert payload["evaluation"]["text"] == "+0.20"
    assert 0 < payload["evaluation"]["fraction"] < 1
    assert payload["best_move"] == "e2e4"


def test_eval_uses_the_configured_depth(client, config):
    assert client.post("/api/engine/eval", json={"fen": START}).json()["depth"] == config.engine_depth


def test_eval_accepts_a_depth_override(client):
    assert client.post("/api/engine/eval", json={"fen": START, "depth": 5}).json()["depth"] == 5


def test_eval_reports_cache_misses_then_hits(client):
    first = client.post("/api/engine/eval", json={"fen": START}).json()
    second = client.post("/api/engine/eval", json={"fen": START}).json()
    assert first["cached"] is False
    assert second["cached"] is True


def test_cached_responses_do_not_call_the_engine(client, fake_engine_for_api):
    client.post("/api/engine/eval", json={"fen": START})
    client.post("/api/engine/eval", json={"fen": START})
    assert fake_engine_for_api.call_count == 1


def test_eval_rejects_an_invalid_fen(client):
    response = client.post("/api/engine/eval", json={"fen": "nope"})
    assert response.status_code == 422
    assert "Invalid FEN" in response.json()["detail"]


def test_eval_rejects_an_out_of_range_depth(client):
    assert client.post("/api/engine/eval", json={"fen": START, "depth": 0}).status_code == 422
    assert client.post("/api/engine/eval", json={"fen": START, "depth": 99}).status_code == 422


def test_mate_scores_are_formatted(client, fake_engine_for_api):
    fake_engine_for_api.results[START] = Eval(mate=3)
    payload = client.post("/api/engine/eval", json={"fen": START}).json()
    assert payload["evaluation"]["text"] == "M3"
    assert payload["evaluation"]["mate"] == 3


def test_eval_is_always_from_whites_perspective(client, fake_engine_for_api):
    """A Black-to-move position still reports White's view."""
    black_to_move = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    fake_engine_for_api.results[black_to_move] = Eval(cp=-150)
    payload = client.post("/api/engine/eval", json={"fen": black_to_move}).json()
    assert payload["evaluation"]["text"].endswith("1.50")
    assert payload["evaluation"]["fraction"] < 0.5


def test_missing_engine_returns_503(real_client, monkeypatch, tmp_path):
    """With no Stockfish binary the endpoint explains itself rather than crashing."""
    from chess_trainer.engine.stockfish import EngineNotAvailable, StockfishEngine

    def boom(self):
        raise EngineNotAvailable("Stockfish not found at /nowhere")

    monkeypatch.setattr(StockfishEngine, "start", boom)
    response = real_client.post("/api/engine/eval", json={"fen": START})
    assert response.status_code == 503
    assert "Stockfish not found" in response.json()["detail"]
