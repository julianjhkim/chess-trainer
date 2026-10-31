from __future__ import annotations


def test_session_starts_unstarted(client):
    payload = client.get("/api/session").json()
    assert payload["started"] is False
    assert payload["current"] is None


def test_session_always_lists_four_steps(client):
    steps = client.get("/api/session").json()["steps"]
    assert [s["position"] for s in steps] == [1, 2, 3, 4]
    assert all(s["enabled"] for s in steps)


def test_starting_without_a_body_selects_everything(client):
    payload = client.post("/api/session/start", json={}).json()
    assert payload["started"] is True
    assert payload["current"] == "inaccuracy_cards"


def test_starting_with_a_subset(client):
    payload = client.post(
        "/api/session/start", json={"steps": ["cards", "play"]}
    ).json()
    assert payload["current"] == "play"
    enabled = {s["step"] for s in payload["steps"] if s["enabled"]}
    assert enabled == {"cards", "play"}


def test_starting_rejects_an_unknown_step(client):
    assert client.post("/api/session/start", json={"steps": ["nope"]}).status_code == 422


def test_completing_a_step_advances(client):
    client.post("/api/session/start", json={})
    payload = client.post("/api/session/complete/inaccuracy_cards").json()
    assert payload["session"]["current"] == "play"


def test_completing_the_play_step_goes_to_the_new_game_review(client):
    client.post("/api/session/start", json={})
    client.post("/api/session/complete/inaccuracy_cards")
    payload = client.post("/api/session/complete/play").json()
    assert payload["session"]["current"] == "review_new_game"


def test_completing_a_step_counts_towards_the_streak(client):
    client.post("/api/session/start", json={})
    payload = client.post("/api/session/complete/inaccuracy_cards").json()
    assert payload["streak"]["current"] == 1
    assert payload["streak"]["active_today"] is True


def test_completing_two_steps_keeps_the_streak_at_one_day(client):
    client.post("/api/session/start", json={})
    client.post("/api/session/complete/inaccuracy_cards")
    payload = client.post("/api/session/complete/play").json()
    assert payload["streak"]["current"] == 1


def test_completing_everything_finishes_the_session(client):
    client.post("/api/session/start", json={"steps": ["cards"]})
    payload = client.post("/api/session/complete/cards").json()
    assert payload["session"]["finished"] is True
    assert payload["session"]["current"] is None


def test_jumping_changes_the_current_step(client):
    client.post("/api/session/start", json={})
    assert client.post("/api/session/jump/cards").json()["current"] == "cards"


def test_jumping_backwards_works(client):
    client.post("/api/session/start", json={})
    client.post("/api/session/jump/cards")
    assert client.post("/api/session/jump/play").json()["current"] == "play"


def test_jumping_to_an_unselected_step_enables_it(client):
    client.post("/api/session/start", json={"steps": ["cards"]})
    payload = client.post("/api/session/jump/play").json()
    enabled = {s["step"] for s in payload["steps"] if s["enabled"]}
    assert {"cards", "play"} <= enabled


def test_jumping_to_an_unknown_step_is_rejected(client):
    assert client.post("/api/session/jump/nonsense").status_code == 422


def test_reset_returns_to_the_start_screen(client):
    client.post("/api/session/start", json={})
    client.post("/api/session/complete/inaccuracy_cards")
    payload = client.post("/api/session/reset").json()
    assert payload["started"] is False
    assert not any(s["completed"] for s in payload["steps"])


def test_session_state_persists_across_requests(client):
    client.post("/api/session/start", json={})
    client.post("/api/session/jump/cards")
    assert client.get("/api/session").json()["current"] == "cards"


def test_starting_at_a_chosen_step(client):
    payload = client.post("/api/session/start", json={"start_at": "cards"}).json()
    assert payload["started"] is True
    assert payload["current"] == "cards"
    assert all(s["enabled"] for s in payload["steps"])


def test_starting_at_an_unknown_step_is_rejected(client):
    assert client.post("/api/session/start", json={"start_at": "nope"}).status_code == 422
