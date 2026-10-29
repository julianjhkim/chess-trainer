from __future__ import annotations

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
MATED = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
PROMO = "8/P7/8/8/8/8/8/K6k w - - 0 1"


def test_state_of_the_start_position(client):
    payload = client.post("/api/board/state", json={"fen": START}).json()
    assert payload["turn"] == "white"
    assert sorted(payload["dests"]["e2"]) == ["e3", "e4"]
    assert payload["game_over"] is False
    assert payload["in_check"] is False


def test_state_defaults_to_the_start_position(client):
    assert client.post("/api/board/state", json={}).json()["fen"] == START


def test_state_rejects_an_invalid_fen(client):
    response = client.post("/api/board/state", json={"fen": "garbage"})
    assert response.status_code == 422
    assert "Invalid FEN" in response.json()["detail"]


def test_state_reports_a_finished_game(client):
    payload = client.post("/api/board/state", json={"fen": MATED}).json()
    assert payload["game_over"] is True
    assert payload["outcome"] == "Black wins by checkmate"


def test_move_returns_san_and_the_next_state(client):
    payload = client.post(
        "/api/board/move", json={"fen": START, "from": "e2", "to": "e4"}
    ).json()
    assert payload["san"] == "e4"
    assert payload["uci"] == "e2e4"
    assert payload["state"]["turn"] == "black"
    assert payload["is_capture"] is False


def test_move_rejects_an_illegal_move(client):
    response = client.post(
        "/api/board/move", json={"fen": START, "from": "e2", "to": "e5"}
    )
    assert response.status_code == 422
    assert "not legal" in response.json()["detail"]


def test_move_auto_promotes_to_a_queen(client):
    payload = client.post(
        "/api/board/move", json={"fen": PROMO, "from": "a7", "to": "a8"}
    ).json()
    assert payload["uci"] == "a7a8q"
    assert payload["promotion"] == "q"
    assert payload["san"].startswith("a8=Q")


def test_move_honours_an_explicit_promotion(client):
    payload = client.post(
        "/api/board/move",
        json={"fen": PROMO, "from": "a7", "to": "a8", "promotion": "n"},
    ).json()
    assert payload["uci"] == "a7a8n"


def test_move_detects_checkmate(client):
    # Scholar's mate: Qxf7#
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    payload = client.post(
        "/api/board/move", json={"fen": fen, "from": "f3", "to": "f7"}
    ).json()
    assert payload["game_over"] is True
    assert payload["outcome"] == "White wins by checkmate"
    assert payload["san"] == "Qxf7#"


def test_move_marks_captures(client):
    fen = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    payload = client.post(
        "/api/board/move", json={"fen": fen, "from": "e4", "to": "d5"}
    ).json()
    assert payload["is_capture"] is True
    assert payload["san"] == "exd5"
