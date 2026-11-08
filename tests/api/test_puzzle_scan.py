"""Making puzzles: paste a game, the engine scans my moves, forced lines are saved."""

from __future__ import annotations

import json
import time

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.connection import connect
from tests.api.test_inaccuracy_cards import NO_NAMES, PGN, make_blunder
from tests.api.test_revision_puzzles import rig_puzzle


def scan(client, pgn=PGN, colour=None) -> dict:
    """Start a scan and wait for it to finish."""
    started = client.post("/api/inaccuracy-cards/scan", json={"pgn": pgn, "colour": colour})
    assert started.status_code == 200, started.text
    for _ in range(200):
        state = client.get("/api/inaccuracy-cards/scan").json()
        if state["status"] != "running":
            return state
        time.sleep(0.02)
    raise AssertionError("the scan never finished")


def test_a_slip_with_a_forced_line_becomes_a_puzzle(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    rig_puzzle(fake_engine_for_api)
    state = scan(client)
    assert state["status"] == "done"
    assert state["total"] == 3  # my three moves
    [found] = state["found"]
    assert (found["move_label"], found["my_moves"], found["created"]) == ("2.Nf3", 2, True)
    assert found["classification"] == "blunder"
    conn = connect(client.app.state.ctx.config.db_path)
    card = repo.get_by_epd(conn, repo.get(conn, 1).epd)
    conn.close()
    assert card.solution == ("d2d4", "e5d4", "d1d4")


def test_a_slip_with_nothing_forced_after_it_is_skipped(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    state = scan(client)
    assert state["found"] == []
    assert state["skipped"] == ["2.Nf3"]
    assert state["counts"]["total"] == 0


def test_the_scan_never_shows_a_solution(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    rig_puzzle(fake_engine_for_api)
    text = json.dumps(scan(client))
    # None of the solution's moves is in the game itself.
    for uci in ("d2d4", "e5d4", "d1d4"):
        assert uci not in text


def test_the_scan_returns_the_game_to_step_through(client, fake_engine_for_api):
    state = scan(client)
    assert [m["san"] for m in state["moves"]] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    assert state["colour"] == "white"


def test_saving_puzzles_completes_the_step_once(client, fake_engine_for_api):
    client.post("/api/session/start", json={})
    make_blunder(fake_engine_for_api, 2, "d2d4")
    rig_puzzle(fake_engine_for_api)
    first = scan(client)
    assert any(s["step"] == "make_card" and s["completed"] for s in first["session"]["steps"])
    assert client.get("/api/inaccuracy-cards/scan").json()["session"] is None


def test_a_game_with_no_puzzles_does_not_count_the_step(client, fake_engine_for_api):
    client.post("/api/session/start", json={})
    assert scan(client)["session"] is None


def test_scanning_the_same_game_again_keeps_one_card(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    rig_puzzle(fake_engine_for_api)
    scan(client)
    again = scan(client)
    assert again["found"][0]["created"] is False
    assert again["counts"]["total"] == 1


def test_the_scan_needs_my_side(client):
    response = client.post("/api/inaccuracy-cards/scan", json={"pgn": NO_NAMES})
    assert response.status_code == 422
    assert "Pick White or Black" in response.json()["detail"]


def test_a_bad_pgn_is_refused_at_once(client):
    response = client.post("/api/inaccuracy-cards/scan", json={"pgn": "hello"})
    assert response.status_code == 422


def test_before_any_scan_there_is_nothing_to_report(client):
    assert client.get("/api/inaccuracy-cards/scan").json()["status"] == "idle"
