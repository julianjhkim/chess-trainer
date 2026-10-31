"""The inaccuracy-card endpoints, and the cards that finished reviews create."""

from __future__ import annotations

from datetime import date

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.connection import connect
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.streak import seoul_day
from tests.api.test_review import STEP, make_blunder, start_review


def finish_a_review(client, fake_engine) -> None:
    """Review a game whose slip is 2.Nf3 (the engine wants 2.d4), and reveal it."""
    make_blunder(fake_engine, 2, "d2d4")
    start_review(client)
    client.post("/api/review/show-answer", json={"step": STEP})


def make_everything_due(client) -> None:
    conn = connect(client.app.state.ctx.config.db_path)
    today = seoul_day.today(tz_name=client.app.state.ctx.config.timezone)
    for card_id in [r["card_id"] for r in conn.execute("SELECT card_id FROM inaccuracy_schedule")]:
        s = repo.get_schedule(conn, card_id)
        repo.upsert_schedule(
            conn,
            ScheduleRow(card_id=card_id, n=s.n, ef=s.ef, interval_days=s.interval_days, due_on=today),
        )
    conn.close()


# -- created by reviews ------------------------------------------------------
def test_finishing_a_review_adds_a_card_due_tomorrow(client, fake_engine_for_api):
    finish_a_review(client, fake_engine_for_api)
    review = client.get(f"/api/review/{STEP}").json()
    added = review["inaccuracy_card"]
    today = seoul_day.today(tz_name=client.app.state.ctx.config.timezone)
    assert added["created"] is True
    assert date.fromisoformat(added["due_on"]) > today


def test_a_clean_game_adds_no_card(client):
    start_review(client)
    client.post("/api/review/acknowledge", json={"step": STEP})
    assert client.get("/api/inaccuracy-cards/state").json()["counts"]["total"] == 0


def test_nothing_is_due_on_the_day_the_card_is_made(client, fake_engine_for_api):
    finish_a_review(client, fake_engine_for_api)
    payload = client.post("/api/inaccuracy-cards/next").json()
    assert payload["exhausted"] is True
    assert payload["counts"]["total"] == 1
    assert payload["counts"]["next_due_on"] is not None


def test_an_empty_deck_is_exhausted_straight_away(client):
    payload = client.post("/api/inaccuracy-cards/next").json()
    assert payload["exhausted"] is True
    assert payload["counts"] == {"due": 0, "relearning": 0, "total": 0, "next_due_on": None}


# -- drilling ----------------------------------------------------------------
def serve(client, fake_engine) -> dict:
    finish_a_review(client, fake_engine)
    make_everything_due(client)
    return client.post("/api/inaccuracy-cards/next").json()


def test_a_due_card_is_the_slip_position_without_its_answer(client, fake_engine_for_api):
    payload = serve(client, fake_engine_for_api)
    card = payload["card"]
    assert card["orientation"] == "white"
    assert card["move_number"] == 2
    assert card["last_move_uci"] == "e7e5"
    assert card["opponent"] == "rival"
    assert "d2d4" not in str(card)
    # What I played is shown while solving -- it is what not to play.
    assert (card["my_move_uci"], card["move_label"]) == ("g1f3", "2.Nf3")


def test_a_wrong_move_is_unlimited_and_evaluated(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    payload = client.post("/api/inaccuracy-cards/attempt", json={"from": "a2", "to": "a3"}).json()
    assert payload["correct"] is False
    assert payload["evaluation"]["text"]
    assert payload["result"] is None


def test_the_engine_move_solves_it_and_reports_the_game_move(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    payload = client.post("/api/inaccuracy-cards/attempt", json={"from": "d2", "to": "d4"}).json()
    assert payload["correct"] and payload["finished"]
    result = payload["result"]
    assert result["answer_san"] == "d4"
    assert result["my_move_san"] == "Nf3"
    assert result["move_label"] == "2.Nf3"
    assert result["grade"]["quality"] == 4
    assert result["grade"]["interval_days"] == 6


def test_the_first_answer_counts_the_step(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    payload = client.post("/api/inaccuracy-cards/attempt", json={"from": "d2", "to": "d4"}).json()
    steps = {s["step"]: s for s in payload["session"]["steps"]}
    assert steps["inaccuracy_cards"]["completed"] is True
    assert payload["streak"]["current"] >= 1


def test_a_hint_names_the_piece_and_caps_the_grade(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    hint = client.post("/api/inaccuracy-cards/hint").json()
    assert hint == {"square": "d2", "piece": "pawn", "text": "Move your pawn on d2."}
    payload = client.post("/api/inaccuracy-cards/attempt", json={"from": "d2", "to": "d4"}).json()
    assert payload["result"]["grade"]["quality"] == 3
    assert payload["result"]["grade"]["description"] == "right with a hint"


def test_showing_the_answer_fails_and_requeues(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    payload = client.post("/api/inaccuracy-cards/show-answer").json()
    assert payload["uci"] == "d2d4"
    grade = payload["result"]["grade"]
    assert grade["quality"] == 1 and not grade["passed"] and grade["requeued"]
    assert payload["result"]["revealed"] is True


def test_a_finished_card_refuses_more_moves(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    client.post("/api/inaccuracy-cards/attempt", json={"from": "d2", "to": "d4"})
    response = client.post("/api/inaccuracy-cards/attempt", json={"from": "a2", "to": "a3"})
    assert response.status_code == 409


def test_no_card_on_screen_is_a_409(client):
    assert client.post("/api/inaccuracy-cards/attempt", json={"from": "a2", "to": "a3"}).status_code == 409
    assert client.post("/api/inaccuracy-cards/hint").status_code == 409


def test_an_illegal_move_is_a_422(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    assert client.post("/api/inaccuracy-cards/attempt", json={"from": "a2", "to": "a6"}).status_code == 422
