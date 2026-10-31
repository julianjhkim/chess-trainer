from __future__ import annotations


def test_streak_is_empty_initially(client):
    payload = client.get("/api/streak").json()
    assert payload == {
        "current": 0,
        "longest": 0,
        "active_today": False,
        "total_days": 0,
    }


def test_streak_reflects_a_completed_step(client):
    client.post("/api/session/start", json={})
    client.post("/api/session/complete/inaccuracy_cards")
    payload = client.get("/api/streak").json()
    assert payload["current"] == 1
    assert payload["longest"] == 1
    assert payload["total_days"] == 1


def test_streak_survives_a_new_client_on_the_same_database(config):
    from fastapi.testclient import TestClient

    from chess_trainer.api.app import create_app

    with TestClient(create_app(config)) as first:
        first.post("/api/session/start", json={})
        first.post("/api/session/complete/cards")

    with TestClient(create_app(config)) as second:
        assert second.get("/api/streak").json()["current"] == 1
