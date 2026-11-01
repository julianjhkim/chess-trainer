"""The revision-card endpoints (internally "inaccuracy cards").

Cards are made by hand: a pasted game and the number of my move that went
wrong. Reviews no longer make them.
"""

from __future__ import annotations

from datetime import date

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.connection import connect
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.streak import seoul_day
from tests.api.test_review import BLACK_PGN, PGN, STEP, make_blunder, start_review

NO_NAMES = "\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n"


def make_card(client, fake_engine, *, move_number=2, pgn=PGN, colour=None):
    """Make a card for my move 2 (2.Nf3), where the engine wants 2.d4."""
    make_blunder(fake_engine, 2, "d2d4", pgn=pgn)
    return client.post(
        "/api/inaccuracy-cards",
        json={"pgn": pgn, "move_number": move_number, "colour": colour},
    )


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


# -- previewing --------------------------------------------------------------
def test_preview_finds_my_move_by_its_number(client):
    payload = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": PGN, "move_number": 2}
    ).json()
    assert payload["colour"] == "white"  # read from my name in the PGN
    assert (payload["ply"], payload["move_label"], payload["my_move_uci"]) == (2, "2.Nf3", "g1f3")
    assert payload["last_move_uci"] == "e7e5"
    assert [m["san"] for m in payload["moves"]] == ["e4", "e5"]
    assert payload["opponent"] == "rival"
    assert payload["existing"] == "none"


def test_preview_as_black_counts_black_moves(client):
    payload = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": BLACK_PGN, "move_number": 2}
    ).json()
    assert payload["colour"] == "black"
    assert payload["move_label"] == "2...Nc6"
    assert [m["san"] for m in payload["moves"]] == ["e4", "e5", "Nf3"]


def test_preview_needs_a_colour_when_the_pgn_does_not_name_me(client):
    response = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": NO_NAMES, "move_number": 2}
    )
    assert response.status_code == 422
    assert "Pick White or Black" in response.json()["detail"]
    picked = client.post(
        "/api/inaccuracy-cards/preview",
        json={"pgn": NO_NAMES, "move_number": 2, "colour": "black"},
    ).json()
    assert picked["move_label"] == "2...Nc6"


def test_preview_of_a_move_the_game_does_not_have(client):
    response = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": PGN, "move_number": 9}
    )
    assert response.status_code == 422
    assert "no move 9" in response.json()["detail"]
    assert "1 to 3" in response.json()["detail"]


def test_preview_of_bad_pgn_is_a_422(client):
    response = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": "hello", "move_number": 1}
    )
    assert response.status_code == 422


# -- making ------------------------------------------------------------------
def test_making_a_card_schedules_it_for_tomorrow(client, fake_engine_for_api):
    payload = make_card(client, fake_engine_for_api).json()
    today = seoul_day.today(tz_name=client.app.state.ctx.config.timezone)
    assert payload["created"] is True
    assert payload["move_label"] == "2.Nf3"
    assert date.fromisoformat(payload["due_on"]) > today
    assert payload["counts"]["total"] == 1
    assert "d2d4" not in str(payload) and "d4" not in payload["move_label"]


def test_the_card_records_the_engine_move_and_the_slip(client, fake_engine_for_api):
    make_card(client, fake_engine_for_api)
    conn = connect(client.app.state.ctx.config.db_path)
    card = repo.get(conn, 1)
    conn.close()
    assert (card.best_move_uci, card.best_move_san) == ("d2d4", "d4")
    assert card.classification == "blunder"
    assert card.game_id and card.game_id.startswith("paste-")


def test_a_move_the_engine_agrees_with_is_refused(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "g1f3")
    response = client.post("/api/inaccuracy-cards", json={"pgn": PGN, "move_number": 2})
    assert response.status_code == 422
    assert "the one you played" in response.json()["detail"]
    assert client.get("/api/inaccuracy-cards/state").json()["counts"]["total"] == 0


def test_making_the_same_card_twice_keeps_one(client, fake_engine_for_api):
    make_card(client, fake_engine_for_api)
    again = make_card(client, fake_engine_for_api).json()
    assert again["created"] is False
    assert again["counts"]["total"] == 1
    preview = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": PGN, "move_number": 2}
    ).json()
    assert preview["existing"] == "active"


def test_a_review_no_longer_makes_a_card(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/show-answer", json={"step": STEP})
    assert "inaccuracy_card" not in client.get(f"/api/review/{STEP}").json()
    assert client.get("/api/inaccuracy-cards/state").json()["counts"]["total"] == 0


def test_nothing_is_due_on_the_day_the_card_is_made(client, fake_engine_for_api):
    make_card(client, fake_engine_for_api)
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
    make_card(client, fake_engine)
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
    # The moves before it can be stepped through; nothing after.
    assert [m["san"] for m in card["moves"]] == ["e4", "e5"]


def test_the_result_opens_the_whole_game(client, fake_engine_for_api):
    serve(client, fake_engine_for_api)
    result = client.post("/api/inaccuracy-cards/show-answer").json()["result"]
    assert [m["san"] for m in result["moves"]] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    assert result["ply"] == 2


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


# -- deleting ----------------------------------------------------------------
def test_deleting_the_card_on_screen_clears_it(client, fake_engine_for_api):
    card = serve(client, fake_engine_for_api)["card"]
    counts = client.delete(f"/api/inaccuracy-cards/{card['id']}").json()
    assert counts == {"due": 0, "relearning": 0, "total": 0, "next_due_on": None}
    assert client.get("/api/inaccuracy-cards/state").json()["card"] is None
    assert client.post("/api/inaccuracy-cards/hint").status_code == 409
    assert client.post("/api/inaccuracy-cards/next").json()["exhausted"] is True


def test_deleting_does_not_count_the_step(client, fake_engine_for_api):
    card = serve(client, fake_engine_for_api)["card"]
    client.delete(f"/api/inaccuracy-cards/{card['id']}")
    session = client.get("/api/session").json()
    step = next(s for s in session["steps"] if s["step"] == "inaccuracy_cards")
    assert step["completed"] is False


def test_deleting_an_unknown_card_is_a_404(client):
    assert client.delete("/api/inaccuracy-cards/999").status_code == 404


def test_making_a_deleted_card_again_restores_it(client, fake_engine_for_api):
    card = serve(client, fake_engine_for_api)["card"]
    client.delete(f"/api/inaccuracy-cards/{card['id']}")
    preview = client.post(
        "/api/inaccuracy-cards/preview", json={"pgn": PGN, "move_number": 2}
    ).json()
    assert preview["existing"] == "deleted"
    again = make_card(client, fake_engine_for_api).json()
    assert again["restored"] is True and again["counts"]["total"] == 1
