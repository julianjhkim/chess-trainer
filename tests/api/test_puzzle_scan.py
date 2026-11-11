"""Making puzzles: paste a game, the engine finds each mistake's punishment."""

from __future__ import annotations

import json
import time

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.connection import connect
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.pgn.positions import from_parsed, walk
from tests.api.test_inaccuracy_cards import NO_NAMES, PGN, make_everything_due

#: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6, as positions; I am White.
GAME = from_parsed(parse_pgn(PGN))


def rig_line(engine, fen: str, line: list[str], good: Eval, reply: str) -> None:
    """Make ``line`` the forced punishment from ``fen``: each of the solver's
    moves the only good one (``good`` against level), the replies the engine's,
    and ``reply`` the opponent's answer to its last move."""
    walked = walk([*line, reply], start_fen=fen)
    for i, move in enumerate(walked):
        engine.best_moves[move.fen_before] = move.uci
        if i % 2 == 0 and i < len(line):
            engine.results[move.fen_before] = good
            engine.restricted_results[move.fen_before] = Eval(cp=0)


#: 2...d5! 3.a3 dxe4!, and White's 4.a4 does not win the pawn back.
PAWN_WON = ("d7d5", "a2a3", "d5e4")


def rig_my_mistake(engine, *, line=PAWN_WON, reply="a3a4", punishable=True) -> None:
    """2.Nf3 throws the game away (0.00 -> -5.00) and 2...d5! 3.a3 dxe4! is the
    only way to punish it, a pawn up. Black's 2...Nc6 keeps the -5.00, so it is
    no mistake."""
    engine.results[GAME[2].fen_before] = Eval(cp=0)
    engine.best_moves[GAME[2].fen_before] = "d2d4"
    engine.results[GAME[3].fen_after] = Eval(cp=-500)
    if punishable:
        rig_line(engine, GAME[2].fen_after, list(line), Eval(cp=-500), reply)
    else:
        engine.best_moves[GAME[2].fen_after] = line[0]
    engine.results[GAME[2].fen_after] = Eval(cp=-500)


def rig_their_mistake(engine) -> None:
    """2...Nc6 throws it away (0.00 -> +5.00); 3.d4! a6 4.dxe5! wins a pawn."""
    engine.results[GAME[3].fen_before] = Eval(cp=0)
    engine.best_moves[GAME[3].fen_before] = "d7d5"
    engine.results[GAME[4].fen_after] = Eval(cp=500)
    rig_line(engine, GAME[3].fen_after, ["d2d4", "a7a6", "d4e5"], Eval(cp=500), "a6a5")


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
    assert (found["solver_moves"], found["ply"], found["classification"]) == (2, 3, "blunder")
    [card] = stored(client)
    assert card.kind == "punish" and card.solver == "black"
    assert card.fen == GAME[2].fen_after  # right after my mistake
    assert card.solution == PAWN_WON
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


def test_a_mistake_punished_in_one_move_is_not_a_puzzle(client, fake_engine_for_api):
    """Too crude to learn from: a piece left hanging, say."""
    rig_my_mistake(fake_engine_for_api, line=("d7d5",), reply="a2a3")
    state = scan(client)
    assert state["found"] == []
    assert state["skipped"] == ["2.Nf3"]


#: 2...d5! 3.exd5 Qxd5!: forced, but level material -- a positional edge.
LEVEL = ("d7d5", "e4d5", "d8d5")


def make_it_an_inaccuracy(engine) -> None:
    """2.Nf3 costs about 13% instead of throwing the game away."""
    engine.results[GAME[2].fen_after] = Eval(cp=-150)
    engine.results[GAME[3].fen_after] = Eval(cp=-150)


def test_after_an_inaccuracy_a_positional_punishment_is_not_a_puzzle(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api, line=LEVEL, reply="b1c3")
    make_it_an_inaccuracy(fake_engine_for_api)
    state = scan(client)
    assert state["found"] == [] and state["skipped"] == ["2.Nf3"]


def test_after_a_mistake_a_positional_punishment_is_a_puzzle(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api, line=LEVEL, reply="b1c3")  # -5.00: a blunder
    [found] = scan(client)["found"]
    assert found["classification"] == "blunder"


def test_material_won_back_by_the_reply_does_not_count(client, fake_engine_for_api):
    """3...dxe4 wins a pawn, but 4.Nxe5 takes one straight back."""
    rig_my_mistake(fake_engine_for_api, reply="f3e5")
    make_it_an_inaccuracy(fake_engine_for_api)
    assert scan(client)["found"] == []


def test_an_inaccuracy_with_a_clear_punishment_is_a_puzzle(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api)  # wins a pawn
    make_it_an_inaccuracy(fake_engine_for_api)
    [found] = scan(client)["found"]
    assert (found["move_label"], found["classification"]) == ("2.Nf3", "inaccuracy")


def test_a_smaller_slip_is_not_scanned(client, fake_engine_for_api):
    rig_my_mistake(fake_engine_for_api)
    fake_engine_for_api.results[GAME[2].fen_after] = Eval(cp=-80)  # about -7%
    fake_engine_for_api.results[GAME[3].fen_after] = Eval(cp=-80)
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
    assert card["my_colour"] == "white"  # the side I had, not the side I play


def test_the_games_next_move_waits_for_the_result(client, fake_engine_for_api):
    card = serve_punishment(client, fake_engine_for_api)
    assert card["my_move_uci"] is None
    client.post("/api/inaccuracy-cards/attempt", json={"from": "d7", "to": "d5"})
    payload = client.post("/api/inaccuracy-cards/attempt", json={"from": "d5", "to": "e4"}).json()
    assert payload["finished"]
    result = payload["result"]
    assert (result["my_move_san"], result["played_label"]) == ("Nc6", "2...Nc6")
    assert result["lichess_url"].endswith("?color=black#3")
