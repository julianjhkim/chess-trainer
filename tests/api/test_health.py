from __future__ import annotations

from chess_trainer import __version__


def test_health_is_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_the_version(client):
    assert client.get("/api/health").json()["version"] == __version__


def test_health_describes_the_engine(client, config):
    engine = client.get("/api/health").json()["engine"]
    assert engine["path"] == str(config.stockfish_path)
    assert engine["depth"] == config.engine_depth
    assert "exists" in engine


def test_health_reports_the_database_and_username(client, config):
    payload = client.get("/api/health").json()
    assert payload["database"] == str(config.db_path)
    assert payload["chesscom_username"] == "test-player"


def test_health_reports_whether_a_lichess_token_is_set(client):
    assert client.get("/api/health").json()["lichess_token_present"] is False


def test_health_reports_the_streak_timezone(client):
    assert client.get("/api/health").json()["timezone"] == "Asia/Seoul"


def test_openapi_schema_is_served(client):
    assert client.get("/openapi.json").status_code == 200
