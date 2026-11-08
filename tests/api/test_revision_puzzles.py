"""Playing a puzzle: the opponent replies, and I go on to the end."""

from __future__ import annotations

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.connection import connect
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.pgn.positions import from_parsed, walk
from tests.api.test_inaccuracy_cards import PGN, make_card, make_everything_due


def rig_puzzle(engine) -> None:
    """2.d4! exd4 3.Qxd4!, each of my moves the only good one; then nothing forced."""
    slip = from_parsed(parse_pgn(PGN))[2].fen_before  # after 1.e4 e5
    after = walk(["d2d4", "e5d4"], start_fen=slip)
    engine.restricted_results[slip] = Eval(cp=-300)
    engine.best_moves[after[0].fen_after] = "e5d4"
    engine.best_moves[after[1].fen_after] = "d1d4"
    engine.results[after[1].fen_after] = Eval(cp=300)
    engine.restricted_results[after[1].fen_after] = Eval(cp=0)


def serve_puzzle(client, engine) -> dict:
    rig_puzzle(engine)
    make_card(client, engine)
    make_everything_due(client)
    client.post("/api/session/start", json={})
    return client.post("/api/inaccuracy-cards/next").json()


def move(client, frm, to) -> dict:
    return client.post("/api/inaccuracy-cards/attempt", json={"from": frm, "to": to}).json()


def test_a_right_move_brings_the_opponents_reply(client, fake_engine_for_api):
    serve_puzzle(client, fake_engine_for_api)
    payload = move(client, "d2", "d4")
    assert payload["correct"] and not payload["finished"]
    assert payload["reply_san"] == "exd4"
    assert [m["san"] for m in payload["played"]] == ["d4", "exd4"]
    assert [m["ply"] for m in payload["played"]] == [2, 3]  # numbered as in the game
    assert payload["result"] is None


def test_the_puzzle_ends_on_my_last_only_move(client, fake_engine_for_api):
    serve_puzzle(client, fake_engine_for_api)
    move(client, "d2", "d4")
    payload = move(client, "d1", "d4")
    assert payload["finished"]
    assert [m["san"] for m in payload["result"]["solution"]] == ["d4", "exd4", "Qxd4"]
    assert payload["result"]["grade"]["quality"] == 4  # no wrong tries


def test_wrong_tries_count_over_the_whole_puzzle(client, fake_engine_for_api):
    serve_puzzle(client, fake_engine_for_api)
    assert not move(client, "a2", "a3")["correct"]
    move(client, "d2", "d4")
    assert not move(client, "b1", "c3")["correct"]
    payload = move(client, "d1", "d4")
    assert payload["result"]["grade"]["quality"] == 2  # two wrong: a fail
    assert payload["result"]["grade"]["requeued"]


def test_one_wrong_try_in_the_whole_puzzle_still_passes(client, fake_engine_for_api):
    serve_puzzle(client, fake_engine_for_api)
    move(client, "d2", "d4")
    move(client, "b1", "c3")
    assert move(client, "d1", "d4")["result"]["grade"]["quality"] == 3


def test_the_hint_is_for_the_step_reached(client, fake_engine_for_api):
    serve_puzzle(client, fake_engine_for_api)
    move(client, "d2", "d4")
    hint = client.post("/api/inaccuracy-cards/hint").json()
    assert hint["square"] == "d1"
    assert hint["piece"] == "queen"


def test_show_answer_plays_out_the_rest(client, fake_engine_for_api):
    serve_puzzle(client, fake_engine_for_api)
    move(client, "d2", "d4")
    payload = client.post("/api/inaccuracy-cards/show-answer").json()
    assert payload["finished"] and payload["san"] == "Qxd4"
    assert payload["result"]["grade"]["quality"] == 1
    assert payload["result"]["revealed"]


def test_the_puzzle_is_never_sent_before_it_is_solved(client, fake_engine_for_api):
    import json

    served = serve_puzzle(client, fake_engine_for_api)
    assert "d1d4" not in json.dumps(served) and "d2d4" not in json.dumps(served)
    assert "d1d4" not in json.dumps(move(client, "d2", "d4"))


def test_a_card_from_before_puzzles_gets_one_when_served(client, fake_engine_for_api):
    rig_puzzle(fake_engine_for_api)
    make_card(client, fake_engine_for_api)
    conn = connect(client.app.state.ctx.config.db_path)
    conn.execute("UPDATE inaccuracy_cards SET solution_uci = NULL")
    conn.commit()
    make_everything_due(client)
    client.post("/api/session/start", json={})
    client.post("/api/inaccuracy-cards/next")
    card = repo.get(conn, 1)
    conn.close()
    assert card.solution == ("d2d4", "e5d4", "d1d4")


def test_a_one_move_card_finishes_on_its_answer(client, fake_engine_for_api):
    make_card(client, fake_engine_for_api)  # nothing rigged: no forced follow-up
    make_everything_due(client)
    client.post("/api/session/start", json={})
    client.post("/api/inaccuracy-cards/next")
    payload = move(client, "d2", "d4")
    assert payload["finished"]
    assert [m["san"] for m in payload["result"]["solution"]] == ["d4"]
