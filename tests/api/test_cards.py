"""The opening-card endpoints, end to end with fakes for Lichess and Stockfish."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def canned_explorer(fake_explorer, explorer_root, explorer_e4, explorer_deep, explorer_thin):
    """Load the real recorded responses for the positions the tests walk."""
    deep = [
        "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6",
        "e1g1", "f6e4", "d2d4", "e4d6", "b5c6", "d7c6",
        "d4e5", "d6f5",
    ]
    fake_explorer.load([], explorer_root)
    fake_explorer.load(["e2e4"], explorer_e4)
    fake_explorer.load(deep, explorer_deep)
    fake_explorer.load([*deep, "h2h3"], explorer_thin)
    # Children of 1.e4 are created without a request, but serving one needs its
    # own record; reuse the e4 response shape so those cards can be prepared.
    for reply in ("c7c5", "e7e5", "e7e6", "c7c6"):
        fake_explorer.load(["e2e4", reply], explorer_e4)
    for first in ("d2d4", "g1f3", "c2c4", "g2g3"):
        fake_explorer.load([first], explorer_e4)
    return fake_explorer


def start_cards(client):
    client.post("/api/session/start", json={})
    return client.post("/api/cards/next").json()


def fen_after(ucis: list[str]) -> str:
    """The position a line reaches, as the engine fake is keyed by FEN."""
    from chess_trainer.openings import line as line_module

    return line_module.position_of(ucis).fen


def engine_plays(fake_engine, ucis: list[str], uci: str) -> None:
    """Make the fake engine's top move in a position be ``uci``."""
    fake_engine.best_moves[fen_after(ucis)] = uci


# -- serving -------------------------------------------------------------
def test_the_first_card_bootstraps_the_tree(client):
    payload = start_cards(client)
    assert payload["card"] is not None
    assert payload["counts"]["new"] == 20  # one per White first move


def test_the_first_card_is_the_most_played_first_move(client):
    card = start_cards(client)["card"]
    assert card["given_move_san"] == "e4"
    assert card["depth"] == 1
    assert card["source"] == "new"


def test_the_card_describes_its_line(client):
    card = start_cards(client)["card"]
    assert card["line_uci"] == "e2e4"
    assert card["line_label"] == "1.e4"
    assert card["replay_ucis"] == []
    assert card["fen_before_given"].startswith("rnbqkbnr/pppppppp")


def test_the_card_says_whose_move_to_find(client):
    assert start_cards(client)["card"]["side_to_move"] == "black"


def test_the_card_carries_its_opening_name(client):
    card = start_cards(client)["card"]
    assert card["opening_label"] == "B00 King's Pawn Game"


def test_the_card_reports_its_mode_and_game_count(client):
    card = start_cards(client)["card"]
    assert card["mode"] == "frequency"
    assert card["position_games"] == 1309466


def test_the_answer_is_not_in_the_payload(client):
    """The move to find must not be discoverable from the card."""
    import json

    card = start_cards(client)["card"]
    assert "answer" not in json.dumps(card).lower()
    assert "c7c5" not in json.dumps(card)


def test_bootstrapping_costs_one_explorer_request(client, fake_explorer):
    client.post("/api/session/start", json={})
    client.post("/api/cards/next")
    # One for the root, one to resolve the served card's answer.
    assert fake_explorer.call_count == 2


def test_state_reports_the_card_on_screen(client):
    start_cards(client)
    payload = client.get("/api/cards/state").json()
    assert payload["card"]["given_move_san"] == "e4"
    assert payload["attempts"] == 0
    assert not payload["finished"]


def test_state_without_a_card(client):
    payload = client.get("/api/cards/state").json()
    assert payload["card"] is None
    assert payload["counts"]["new"] == 0


# -- answering -----------------------------------------------------------
def test_a_wrong_move_is_rejected_with_an_evaluation(client):
    start_cards(client)
    payload = client.post(
        "/api/cards/attempt", json={"from": "a7", "to": "a6"}
    ).json()
    assert payload["correct"] is False
    assert payload["san"] == "a6"
    assert payload["attempts"] == 1
    assert payload["evaluation"]["text"]
    assert not payload["finished"]
    assert payload["stats"] is None


def test_retries_are_unlimited(client):
    start_cards(client)
    for _ in range(10):
        response = client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"})
        assert response.status_code == 200
    assert response.json()["attempts"] == 10


def test_every_attempt_gets_its_own_evaluation(client):
    start_cards(client)
    first = client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"}).json()
    second = client.post("/api/cards/attempt", json={"from": "h7", "to": "h6"}).json()
    assert first["evaluation"]["fraction"] is not None
    assert second["evaluation"]["fraction"] is not None


def test_the_right_move_finishes_the_card(client):
    start_cards(client)
    payload = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()
    assert payload["correct"] is True
    assert payload["finished"] is True
    assert payload["answer_san"] == "c5"


def test_an_illegal_move_is_a_422(client):
    start_cards(client)
    response = client.post("/api/cards/attempt", json={"from": "a7", "to": "a4"})
    assert response.status_code == 422
    assert "not legal" in response.json()["detail"]


def test_answering_without_a_card_is_a_409(client):
    assert client.post("/api/cards/attempt", json={"from": "e2", "to": "e4"}).status_code == 409


def test_answering_a_finished_card_is_a_409(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"})
    response = client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"})
    assert response.status_code == 409
    assert "finished" in response.json()["detail"]


# -- grading -------------------------------------------------------------
def test_a_second_try_still_passes(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"})
    grade = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["grade"]
    assert grade["quality"] == 3
    assert grade["description"] == "right on the 2nd try"
    assert grade["passed"]


def test_a_third_try_fails_and_says_how_many_went_wrong(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"})
    client.post("/api/cards/attempt", json={"from": "h7", "to": "h6"})
    grade = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["grade"]
    assert grade["quality"] == 2
    assert grade["description"] == "right after 2 wrong tries"
    assert not grade["passed"]
    assert grade["requeued"]
    assert grade["interval_days"] == 1


def test_a_first_try_grades_four(client):
    start_cards(client)
    grade = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["grade"]
    assert grade["quality"] == 4
    assert grade["description"] == "right first time"
    assert grade["passed"]
    assert grade["was_new"]
    assert grade["interval_days"] == 1


def test_a_retry_grades_three(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"})
    grade = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["grade"]
    assert grade["quality"] == 3
    assert grade["passed"]
    assert grade["ef"] == pytest.approx(2.36)


def test_revealing_the_answer_grades_one(client):
    start_cards(client)
    payload = client.post("/api/cards/show-answer").json()
    assert payload["answer_san"] == "c5"
    assert payload["grade"]["quality"] == 1
    assert not payload["grade"]["passed"]
    assert payload["grade"]["requeued"]


def test_a_failed_card_is_counted_as_relearning(client):
    start_cards(client)
    payload = client.post("/api/cards/show-answer").json()
    assert payload["counts"]["relearning"] == 1


def test_showing_the_answer_without_a_card_is_a_409(client):
    assert client.post("/api/cards/show-answer").status_code == 409


# -- the stats table -----------------------------------------------------
def test_the_stats_table_appears_once_answered(client):
    start_cards(client)
    table = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["stats"]
    assert table["total_games"] == 1309466
    assert table["mode"] == "frequency"
    assert len(table["rows"]) == 19


def test_the_stats_table_marks_the_answer(client):
    start_cards(client)
    table = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["stats"]
    answers = [r for r in table["rows"] if r["is_answer"]]
    assert [r["san"] for r in answers] == ["c5"]


def test_the_stats_table_has_the_spec_columns(client):
    start_cards(client)
    table = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["stats"]
    row = table["rows"][0]
    assert row["san"] == "c5"
    assert row["share"] > 45
    assert row["games"] == 601092
    assert row["white"] and row["draws"] and row["black"]
    assert row["average_rating"] == 2401


def test_a_frequency_table_still_has_no_engine_note(client):
    """Marking the engine's move is not the same as being answered by it."""
    start_cards(client)
    table = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["stats"]
    assert table["engine_note"] is None


def test_the_stats_table_marks_both_moves_when_they_differ(
    client, fake_engine_for_api
):
    engine_plays(fake_engine_for_api, ["e2e4"], "e7e5")
    start_cards(client)
    table = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["stats"]
    assert [r["san"] for r in table["rows"] if r["is_most_played"]] == ["c5"]
    assert [r["san"] for r in table["rows"] if r["is_engine_move"]] == ["e5"]
    assert [r["san"] for r in table["rows"] if r["is_answer"]] == ["c5"]


def test_one_row_carries_both_marks_when_they_agree(client, fake_engine_for_api):
    engine_plays(fake_engine_for_api, ["e2e4"], "c7c5")
    start_cards(client)
    table = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()["stats"]
    row = table["rows"][0]
    assert row["san"] == "c5"
    assert row["is_answer"] and row["is_engine_move"] and row["is_most_played"]


def test_the_revealed_table_marks_them_too(client, fake_engine_for_api):
    engine_plays(fake_engine_for_api, ["e2e4"], "e7e5")
    start_cards(client)
    table = client.post("/api/cards/show-answer").json()["stats"]
    assert [r["san"] for r in table["rows"] if r["is_engine_move"]] == ["e5"]
    assert [r["san"] for r in table["rows"] if r["is_most_played"]] == ["c5"]


def test_the_stats_table_also_appears_when_revealed(client):
    start_cards(client)
    payload = client.post("/api/cards/show-answer").json()
    assert payload["stats"]["total_games"] == 1309466


# -- does the engine agree with the masters? -----------------------------
def test_the_card_says_when_the_engine_agrees(client, fake_engine_for_api):
    engine_plays(fake_engine_for_api, ["e2e4"], "c7c5")
    card = start_cards(client)["card"]
    assert card["engine_agrees"] is True


def test_the_card_says_when_the_engine_disagrees(client, fake_engine_for_api):
    engine_plays(fake_engine_for_api, ["e2e4"], "e7e5")
    card = start_cards(client)["card"]
    assert card["engine_agrees"] is False


def test_the_agreement_does_not_name_either_move(client, fake_engine_for_api):
    """A bare yes/no: naming the engine's move would give the answer away."""
    import json

    engine_plays(fake_engine_for_api, ["e2e4"], "e7e5")
    card = start_cards(client)["card"]
    assert card["engine_agrees"] is False
    assert "e7e5" not in json.dumps(card)
    assert "c7c5" not in json.dumps(card)


def test_an_engine_mode_card_reports_no_agreement(client, fake_engine_for_api):
    """Answered by the engine already, so there is nothing to compare."""
    deep = [
        "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6",
        "e1g1", "f6e4", "d2d4", "e4d6", "b5c6", "d7c6",
        "d4e5", "d6f5",
    ]
    thin = [*deep, "h2h3"]
    engine_plays(fake_engine_for_api, thin, "d8d1")
    card = _serve_card_for_line(client, thin)
    assert card["mode"] == "engine"
    assert card["engine_agrees"] is None


def test_the_card_state_reports_the_agreement_too(client, fake_engine_for_api):
    engine_plays(fake_engine_for_api, ["e2e4"], "e7e5")
    start_cards(client)
    assert client.get("/api/cards/state").json()["card"]["engine_agrees"] is False


def test_the_engine_is_searched_once_per_position(client, fake_engine_for_api):
    """Serving a card again reads the cached search rather than repeating it."""
    engine_plays(fake_engine_for_api, ["e2e4"], "e7e5")
    start_cards(client)
    searches = [c for c in fake_engine_for_api.calls if c[0] == fen_after(["e2e4"])]
    assert len(searches) == 1

    client.get("/api/cards/state")
    repeated = [c for c in fake_engine_for_api.calls if c[0] == fen_after(["e2e4"])]
    assert len(repeated) == 1


def _serve_card_for_line(client, ucis: list[str]):
    """Serve a card for ``ucis``, as the only one in the tree.

    The queue runs breadth-first, so a deep position would never come up on
    its own; the bootstrapped cards are cleared out of its way.
    """
    from chess_trainer.db import cards_repo
    from chess_trainer.db.connection import transaction
    from chess_trainer.openings import line as line_module

    start_cards(client)
    conn = client.app.state.ctx.conn
    position = line_module.position_of(ucis)
    with transaction(conn):
        conn.execute("DELETE FROM cards")
    cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd,
            fen=position.fen,
            line_uci=position.line_uci,
            depth=position.depth,
            side_to_move=position.side_to_move,
            given_move_uci=ucis[-1],
            given_move_san="h3",
            status=cards_repo.STATUS_ACTIVE,
            position_games=11,
            queue_seq=1,
        ),
    )
    return client.post("/api/cards/next").json()["card"]


# -- the tree grows ------------------------------------------------------
def test_answering_correctly_unlocks_the_branches(client):
    start_cards(client)
    payload = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()
    assert payload["branches_created"] == 4
    assert payload["counts"]["new"] == 23  # 20 - 1 answered + 4 new


def test_failing_does_not_unlock_the_branches(client):
    """Branches appear only once a card has actually been got right."""
    start_cards(client)
    payload = client.post("/api/cards/show-answer").json()
    assert payload["branches_created"] == 0
    assert payload["counts"]["new"] == 19


def test_branches_are_not_created_twice(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"})
    from chess_trainer.db import cards_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    assert cards_repo.count(conn) == 24
    conn.close()


def test_breadth_first_order_is_kept(client):
    """After 1.e4 is answered, the next card is still a first move."""
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"})
    card = client.post("/api/cards/next").json()["card"]
    assert card["depth"] == 1
    assert card["given_move_san"] == "d4"


# -- the session and the streak -----------------------------------------
def test_the_first_answer_marks_the_step_and_moves_the_streak(client):
    start_cards(client)
    payload = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()
    completed = [s["step"] for s in payload["session"]["steps"] if s["completed"]]
    assert "cards" in completed
    assert payload["streak"]["current"] == 1


def test_the_step_stays_current_so_the_drill_continues(client):
    """Marking the cards step done must not navigate away from it."""
    client.post("/api/session/start", json={"steps": ["cards"]})
    client.post("/api/cards/next")
    payload = client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"}).json()
    assert payload["session"]["current"] == "cards"


def test_the_streak_is_not_counted_twice(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"})
    second = client.post("/api/cards/next").json()
    assert second["card"] is not None
    assert client.get("/api/streak").json()["total_days"] == 1


def test_a_card_answer_is_logged(client):
    start_cards(client)
    client.post("/api/cards/attempt", json={"from": "a7", "to": "a6"})
    client.post("/api/cards/attempt", json={"from": "c7", "to": "c5"})

    from chess_trainer.db import review_log_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    rows = review_log_repo.recent(conn)
    assert len(rows) == 1
    assert rows[0].quality == 3
    assert rows[0].attempts == 2
    assert rows[0].was_new
    conn.close()


# -- no token ------------------------------------------------------------
def test_without_a_lichess_token_the_endpoint_explains_itself(config):
    from fastapi.testclient import TestClient

    from chess_trainer.api.app import create_app

    assert config.lichess_token is None
    with TestClient(create_app(config)) as client:
        response = client.post("/api/cards/next")
        assert response.status_code == 503
        assert "Lichess API token" in response.json()["detail"]
        assert "oauth/token/create" in response.json()["detail"]


# -- explorer failures ---------------------------------------------------
def test_an_explorer_outage_is_a_502(client, fake_explorer):
    from chess_trainer.explorer.lichess_client import ExplorerUnavailable

    fake_explorer.error = ExplorerUnavailable("Could not reach the Lichess explorer")
    client.post("/api/session/start", json={})
    response = client.post("/api/cards/next")
    assert response.status_code == 502
    assert "Could not reach" in response.json()["detail"]


def test_a_rate_limit_is_surfaced(client, fake_explorer):
    from chess_trainer.explorer.lichess_client import ExplorerRateLimited

    fake_explorer.error = ExplorerRateLimited("Lichess is rate limiting")
    client.post("/api/session/start", json={})
    assert client.post("/api/cards/next").status_code == 502
