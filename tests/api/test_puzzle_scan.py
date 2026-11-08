"""Making puzzles: paste a game, the engine finds each mistake's punishment."""

from __future__ import annotations

import json
import time

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.connection import connect
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.pgn.positions import from_parsed
from tests.api.test_inaccuracy_cards import NO_NAMES, PGN, make_everything_due

#: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6, as positions; I am White.
GAME = from_parsed(parse_pgn(PGN))


def rig_my_mistake(engine, *, punishable=True) -> None:
    """2.Nf3 throws the game away (0.00 -> -5.00); 2...d5! is the only way to
    punish it. Black's 2...Nc6 keeps the -5.00, so it is no mistake."""
    engine.results[GAME[2].fen_before] = Eval(cp=0)
    engine.best_moves[GAME[2].fen_before] = "d2d4"
    engine.results[GAME[2].fen_after] = Eval(cp=-500)
    engine.results[GAME[3].fen_after] = Eval(cp=-500)
    engine.best_moves[GAME[2].fen_after] = "d7d5"
    if punishable:
        engine.restricted_results[GAME[2].fen_after] = Eval(cp=0)


def rig_their_mistake(engine) -> None:
    """2...Nc6 throws it away (0.00 -> +5.00); 3.d4! is the only punishment."""
    engine.results[GAME[3].fen_before] = Eval(cp=0)
    engine.best_moves[GAME[3].fen_before] = "d7d5"
    engine.results[GAME[3].fen_after] = Eval(cp=500)
    engine.results[GAME[4].fen_after] = Eval(cp=500)
    engine.best_moves[GAME[3].fen_after] = "d2d4"
    engine.restricted_results[GAME[3].fen_after] = Eval(cp=0)


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


def stored(client):
    conn = connect(client.app.state.ctx.config.db_path)
    cards = [repo.get(conn, r[0]) for r in conn.execute("SELECT id FROM inaccuracy_cards")]
    conn.close()
    return cards


def test_my_mistake_is_punished_from_my_opponents_side(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api)
    state = scan(client)
    assert state["status"] == "done"
    assert state["total"] == 6  # every move, both sides'
    [found] = state["found"]
    assert (found["move_label"], found["slip_mine"], found["solver_colour"]) == ("2.Nf3", True, "black")
    assert (found["solver_moves"], found["ply"], found["classification"]) == (1, 3, "blunder")
    [card] = stored(client)
    assert card.kind == "punish" and card.solver == "black"
    assert card.fen == GAME[2].fen_after  # right after my mistake
    assert card.solution == ("d7d5",)
    assert card.my_move_uci == "b8c6"  # how the game went on


def test_my_opponents_mistake_is_mine_to_punish(client, fake_engine_for_api):
    rig_their_mistake(fake_engine_for_api)
    [found] = scan(client)["found"]
    assert (found["move_label"], found["slip_mine"], found["solver_colour"]) == ("2...Nc6", False, "white")


def test_a_mistake_with_no_clear_punishment_is_skipped(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api, punishable=False)
    state = scan(client)
    assert state["found"] == []
    assert state["skipped"] == ["2.Nf3"]
    assert state["counts"]["total"] == 0


def test_an_inaccuracy_is_not_scanned(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api)
    fake_engine_for_api.results[GAME[2].fen_after] = Eval(cp=-150)  # about -13%
    fake_engine_for_api.results[GAME[3].fen_after] = Eval(cp=-150)
    state = scan(client)
    assert state["found"] == [] and state["skipped"] == []


def test_the_scan_never_shows_a_solution(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api)
    assert "d7d5" not in json.dumps(scan(client))  # not a move of the game


def test_the_scan_returns_the_game_to_step_through(client, fake_engine_for_api):
    state = scan(client)
    assert [m["san"] for m in state["moves"]] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    assert state["colour"] == "white"


def test_saving_puzzles_completes_the_step_once(client, fake_engine_for_api):
    client.post("/api/session/start", json={})
    rig_my_mistake(fake_engine_for_api)
    first = scan(client)
    assert any(s["step"] == "make_card" and s["completed"] for s in first["session"]["steps"])
    assert client.get("/api/inaccuracy-cards/scan").json()["session"] is None


def test_a_game_with_no_puzzles_does_not_count_the_step(client, fake_engine_for_api):
    client.post("/api/session/start", json={})
    assert scan(client)["session"] is None


def test_scanning_the_same_game_again_keeps_one_card(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api)
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


# -- playing a punishment puzzle ---------------------------------------------
def serve_punishment(client, engine) -> dict:
    rig_my_mistake(engine)
    scan(client)
    make_everything_due(client)
    client.post("/api/session/start", json={})
    return client.post("/api/inaccuracy-cards/next").json()["card"]


def test_a_punishment_is_played_from_the_punishing_side(client, fake_engine_for_api):
    card = serve_punishment(client, fake_engine_for_api)
    assert (card["kind"], card["orientation"], card["slip_mine"]) == ("punish", "black", True)
    assert card["move_label"] == "2.Nf3"
    assert card["last_move_uci"] == "g1f3"  # the mistake, just played
    assert [m["san"] for m in card["moves"]] == ["e4", "e5", "Nf3"]


def test_the_games_next_move_waits_for_the_result(client, fake_engine_for_api):
    card = serve_punishment(client, fake_engine_for_api)
    assert card["my_move_uci"] is None
    payload = client.post("/api/inaccuracy-cards/attempt", json={"from": "d7", "to": "d5"}).json()
    assert payload["finished"]
    result = payload["result"]
    assert (result["my_move_san"], result["played_label"]) == ("Nc6", "2...Nc6")
    assert result["lichess_url"].endswith("?color=black#3")
