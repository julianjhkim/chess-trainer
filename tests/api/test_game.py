from __future__ import annotations

from chess_trainer.chesscom.client import ChessComUnavailable, PlayerNotFound

PGN = '[White "test-player"]\n[Black "rival"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n'
BLACK_PGN = '[White "rival"]\n[Black "test-player"]\n[Result "0-1"]\n\n1. e4 e5 0-1\n'


def raw(
    game_id="g1",
    end_time=1000,
    white="test-player",
    black="rival",
    rules="chess",
    pgn=PGN,
):
    return {
        "uuid": game_id,
        "url": f"https://www.chess.com/game/live/{game_id}",
        "pgn": pgn,
        "rules": rules,
        "time_class": "rapid",
        "end_time": end_time,
        "white": {"username": white, "result": "win"},
        "black": {"username": black, "result": "resigned"},
    }


# -- /latest -------------------------------------------------------------
def test_latest_is_empty_initially(client):
    assert client.get("/api/game/latest").json() == {"game": None}


def test_latest_returns_a_stored_game(client, fake_chesscom):
    fake_chesscom.set_games([raw()])
    client.post("/api/game/fetch-latest")
    game = client.get("/api/game/latest").json()["game"]
    assert game["id"] == "g1"
    assert game["my_colour"] == "white"
    assert game["move_count"] == 4


def test_latest_does_not_hit_the_network(client, fake_chesscom):
    client.get("/api/game/latest")
    assert fake_chesscom.calls == 0


# -- /fetch-latest -------------------------------------------------------
def test_fetch_latest_stores_the_newest_game(client, fake_chesscom):
    fake_chesscom.set_games([raw("old", 100), raw("new", 900)])
    game = client.post("/api/game/fetch-latest").json()["game"]
    assert game["id"] == "new"


def test_fetch_latest_detects_my_colour(client, fake_chesscom):
    fake_chesscom.set_games(
        [raw(white="rival", black="test-player", pgn=BLACK_PGN)]
    )
    game = client.post("/api/game/fetch-latest").json()["game"]
    assert game["my_colour"] == "black"
    assert game["opponent"] == "rival"


def test_fetch_latest_ignores_games_i_did_not_play(client, fake_chesscom):
    fake_chesscom.set_games([raw(white="alice", black="bob")])
    assert client.post("/api/game/fetch-latest").status_code == 502


def test_fetch_latest_reports_the_opponent(client, fake_chesscom):
    fake_chesscom.set_games([raw()])
    assert client.post("/api/game/fetch-latest").json()["game"]["opponent"] == "rival"


def test_fetch_latest_with_no_games_is_a_502(client, fake_chesscom):
    fake_chesscom.set_games([])
    response = client.post("/api/game/fetch-latest")
    assert response.status_code == 502
    assert "No reviewable games" in response.json()["detail"]


def test_fetch_latest_surfaces_an_unknown_player(client, fake_chesscom):
    fake_chesscom.error = PlayerNotFound("chess.com has no player called 'x'")
    response = client.post("/api/game/fetch-latest")
    assert response.status_code == 502
    assert "no player called" in response.json()["detail"]


def test_fetch_latest_surfaces_an_outage(client, fake_chesscom):
    fake_chesscom.error = ChessComUnavailable("Could not reach chess.com")
    assert client.post("/api/game/fetch-latest").status_code == 502


def test_fetch_latest_skips_variants(client, fake_chesscom):
    fake_chesscom.set_games([raw("v", 900, rules="chess960"), raw("std", 100)])
    assert client.post("/api/game/fetch-latest").json()["game"]["id"] == "std"


def test_fetching_twice_does_not_duplicate(client, fake_chesscom):
    fake_chesscom.set_games([raw()])
    client.post("/api/game/fetch-latest")
    client.post("/api/game/fetch-latest")
    from chess_trainer.db import games_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    assert games_repo.count(conn) == 1
    conn.close()


# -- /baseline -----------------------------------------------------------
def test_baseline_records_the_current_latest(client, fake_chesscom):
    fake_chesscom.set_games([raw()])
    assert client.post("/api/game/baseline").json()["game"]["id"] == "g1"


def test_baseline_tolerates_an_outage(client, fake_chesscom):
    """A chess.com failure here must not block the play step."""
    fake_chesscom.error = ChessComUnavailable("down")
    response = client.post("/api/game/baseline")
    assert response.status_code == 200
    assert response.json()["game"] is None


def test_baseline_with_no_games_is_not_an_error(client, fake_chesscom):
    fake_chesscom.set_games([])
    assert client.post("/api/game/baseline").json()["game"] is None


# -- /poll-new -----------------------------------------------------------
def test_polling_finds_a_game_newer_than_the_baseline(client, fake_chesscom):
    fake_chesscom.set_games([raw("first", 100)])
    client.post("/api/game/baseline")
    fake_chesscom.set_games([raw("first", 100), raw("second", 500)])

    payload = client.post("/api/game/poll-new", json={"budget_seconds": 1}).json()
    assert payload["found"]
    assert payload["game"]["id"] == "second"


def test_polling_does_not_return_the_baseline_game(client, fake_chesscom):
    fake_chesscom.set_games([raw("only", 100)])
    client.post("/api/game/baseline")
    payload = client.post("/api/game/poll-new", json={"budget_seconds": 1}).json()
    assert not payload["found"]
    assert payload["game"] is None


def test_polling_reports_the_total_budget(client, fake_chesscom):
    fake_chesscom.set_games([raw()])
    payload = client.post("/api/game/poll-new", json={"budget_seconds": 1}).json()
    assert payload["total_budget_seconds"] == 120.0


def test_polling_with_no_baseline_accepts_any_game(client, fake_chesscom):
    fake_chesscom.set_games([raw("whatever", 10)])
    payload = client.post("/api/game/poll-new", json={"budget_seconds": 1}).json()
    assert payload["found"]


def test_polling_counts_attempts(client, fake_chesscom):
    fake_chesscom.set_games([raw("only", 100)])
    client.post("/api/game/baseline")
    payload = client.post("/api/game/poll-new", json={"budget_seconds": 1}).json()
    assert payload["attempts"] >= 1


def test_polling_rejects_an_excessive_budget(client):
    assert client.post("/api/game/poll-new", json={"budget_seconds": 600}).status_code == 422


def test_polling_rejects_a_negative_budget(client):
    assert client.post("/api/game/poll-new", json={"budget_seconds": -1}).status_code == 422


def test_an_unknown_player_while_polling_is_a_502(client, fake_chesscom):
    fake_chesscom.error = PlayerNotFound("no such player")
    assert client.post("/api/game/poll-new", json={"budget_seconds": 1}).status_code == 502


# -- /paste --------------------------------------------------------------
def test_pasting_a_pgn_stores_it(client):
    game = client.post("/api/game/paste", json={"pgn": PGN}).json()["game"]
    assert game["source"] == "paste"
    assert game["move_count"] == 4
    assert game["my_colour"] == "white"


def test_pasting_detects_my_colour(client):
    game = client.post("/api/game/paste", json={"pgn": BLACK_PGN}).json()["game"]
    assert game["my_colour"] == "black"


def test_pasting_someone_elses_game_defaults_to_white(client):
    other = '[White "alice"]\n[Black "bob"]\n\n1. e4 e5 *\n'
    assert client.post("/api/game/paste", json={"pgn": other}).json()["game"]["my_colour"] == "white"


def test_pasting_the_same_pgn_twice_is_one_game(client):
    first = client.post("/api/game/paste", json={"pgn": PGN}).json()["game"]["id"]
    second = client.post("/api/game/paste", json={"pgn": PGN}).json()["game"]["id"]
    assert first == second


def test_pasting_rubbish_is_rejected(client):
    response = client.post("/api/game/paste", json={"pgn": "not a pgn"})
    assert response.status_code == 422


def test_pasting_a_truncating_pgn_is_rejected(client):
    bad = '[White "a"]\n[Black "b"]\n\n1. e4 e5 2. Qh8 *\n'
    response = client.post("/api/game/paste", json={"pgn": bad})
    assert response.status_code == 422
    assert "could not be read in full" in response.json()["detail"]


def test_pasting_an_empty_string_is_rejected(client):
    assert client.post("/api/game/paste", json={"pgn": ""}).status_code == 422


def test_a_pasted_game_becomes_the_latest(client):
    client.post("/api/game/paste", json={"pgn": PGN})
    assert client.get("/api/game/latest").json()["game"]["source"] == "paste"


def test_pasting_a_real_chesscom_pgn(client, chesscom_pgn):
    game = client.post("/api/game/paste", json={"pgn": chesscom_pgn}).json()["game"]
    assert game["move_count"] == 22
    assert game["my_colour"] == "white"
    assert game["end_time"] == 1736942614
