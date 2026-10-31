"""The review endpoints, end to end against a fake engine."""

from __future__ import annotations

import time

from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.parse import parse_pgn
from chess_trainer.pgn.positions import from_parsed

PGN = '[White "test-player"]\n[Black "rival"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n'
BLACK_PGN = '[White "rival"]\n[Black "test-player"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n'
STEP = "review_new_game"


def positions(pgn=PGN):
    return from_parsed(parse_pgn(pgn))


def make_blunder(engine, ply: int, best_move: str, pgn=PGN) -> None:
    """Rig the fake engine so my move at `ply` looks like a blunder."""
    target = positions(pgn)[ply]
    worse = Eval(cp=-900) if target.mover_is_white else Eval(cp=900)
    engine.results[target.fen_before] = Eval(cp=0)
    engine.results[target.fen_after] = worse
    engine.best_moves[target.fen_before] = best_move


def wait_until_ready(client, step=STEP, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/api/review/{step}").json()
        if payload["status"] != "analysing":
            return payload
        time.sleep(0.02)
    raise AssertionError("review did not finish analysing")


def start_review(client, pgn=PGN, step=STEP):
    client.post("/api/game/paste", json={"pgn": pgn})
    client.post("/api/session/start", json={"start_at": step})
    client.post("/api/review/start", json={"step": step})
    return wait_until_ready(client, step)


# -- starting ------------------------------------------------------------
def test_starting_without_a_game_is_a_404(client):
    response = client.post("/api/review/start", json={"step": STEP})
    assert response.status_code == 404
    assert "No game to review" in response.json()["detail"]


def test_starting_returns_immediately_while_analysing(client):
    client.post("/api/game/paste", json={"pgn": PGN})
    payload = client.post("/api/review/start", json={"step": STEP}).json()
    assert payload["status"] in {"analysing", "ready"}
    assert payload["total_moves"] == 3
    assert payload["game"]["move_count"] == 6


def test_the_review_becomes_ready(client):
    payload = start_review(client)
    assert payload["status"] == "ready"
    assert payload["progress"] == 1.0


def test_a_clean_game_reports_no_inaccuracy(client):
    payload = start_review(client)
    assert payload["no_inaccuracy"]
    assert payload["finished"]
    assert payload["summary"]["found_an_inaccuracy"] is False


def test_a_blunder_produces_a_target(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    payload = start_review(client)
    assert not payload["no_inaccuracy"]
    assert payload["target"]["ply"] == 2
    assert payload["target"]["move_number"] == 2
    assert payload["target"]["replay_ucis"] == ["e2e4", "e7e5"]


def test_the_target_does_not_leak_the_answer(client, fake_engine_for_api):
    """The accepted move must not be discoverable from the review state."""
    make_blunder(fake_engine_for_api, 2, "d2d4")
    payload = start_review(client)
    blob = str(payload["target"])
    assert "d2d4" not in blob
    assert "best_move" not in blob
    assert payload["summary"] is None


# -- browsing the game's moves -------------------------------------------
def test_an_open_drill_lists_only_the_moves_before_the_target(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    payload = start_review(client)
    assert [m["uci"] for m in payload["moves"]] == ["e2e4", "e7e5"]


def test_the_move_list_does_not_leak_the_answer_or_my_move(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    blob = str(start_review(client)["moves"])
    assert "d2d4" not in blob
    assert "g1f3" not in blob


def test_listed_moves_carry_what_the_board_needs(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    first, second = start_review(client)["moves"]
    assert first["san"] == "e4"
    assert first["label"] == "1.e4"
    assert first["fen_after"] == second["fen_before"]
    assert first["is_mine"] is True
    assert second["is_mine"] is False


def test_solving_opens_the_whole_game(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"}
    ).json()
    assert len(payload["review"]["moves"]) == 6
    assert client.get(f"/api/review/{STEP}").json()["moves"][2]["san"] == "Nf3"


def test_revealing_opens_the_whole_game(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post("/api/review/show-answer", json={"step": STEP}).json()
    assert len(payload["review"]["moves"]) == 6


def test_a_clean_game_lists_every_move(client):
    payload = start_review(client)
    assert len(payload["moves"]) == 6


def test_moves_are_mine_by_colour_when_i_played_black(client):
    payload = start_review(client, pgn=BLACK_PGN)
    assert [m["is_mine"] for m in payload["moves"]] == [False, True] * 3


# -- how the game went ----------------------------------------------------
def test_a_clean_win_is_reported_as_a_win(client):
    won = '[White "test-player"]\n[Black "rival"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n'
    payload = start_review(client, pgn=won)
    assert payload["no_inaccuracy"]
    assert payload["game"]["my_outcome"] == "win"


def test_a_draw_is_reported_as_a_draw(client):
    drawn = '[White "rival"]\n[Black "test-player"]\n[Result "1/2-1/2"]\n\n1. e4 e5 1/2-1/2\n'
    assert start_review(client, pgn=drawn)["game"]["my_outcome"] == "draw"


def test_an_unfinished_game_has_no_outcome(client):
    assert start_review(client)["game"]["my_outcome"] is None


# -- the Lichess link ------------------------------------------------------
def test_no_lichess_link_while_still_solving(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    assert start_review(client)["lichess_url"] is None


def test_a_finished_review_links_to_lichess_at_the_slip(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post("/api/review/show-answer", json={"step": STEP}).json()
    url = payload["review"]["lichess_url"]
    assert url.startswith("https://lichess.org/analysis/pgn/1.e4")
    assert url.endswith("?color=white#2")


def test_the_lichess_link_carries_no_player_names(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    url = client.post("/api/review/show-answer", json={"step": STEP}).json()["review"]["lichess_url"]
    assert "test-player" not in url and "rival" not in url


def test_a_clean_game_links_to_lichess_from_the_start(client):
    url = start_review(client, pgn=BLACK_PGN)["lichess_url"]
    assert url.endswith("?color=black#0")


# -- hints ---------------------------------------------------------------
def test_a_hint_names_the_piece_but_not_its_destination(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post("/api/review/hint", json={"step": STEP}).json()
    assert payload["hint"] == {"square": "d2", "piece": "pawn", "text": "Move your pawn on d2."}
    assert "d4" not in str(payload)
    assert payload["review"]["used_hint"] is True
    assert payload["review"]["finished"] is False


def test_the_hint_is_part_of_the_review_state(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    assert client.get(f"/api/review/{STEP}").json()["hint"] is None
    client.post("/api/review/hint", json={"step": STEP})
    assert client.get(f"/api/review/{STEP}").json()["hint"]["square"] == "d2"


def test_a_hint_is_recorded_in_the_summary_and_history(client, fake_engine_for_api):
    from chess_trainer.db import game_reviews_repo

    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/hint", json={"step": STEP})
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"}
    ).json()
    assert payload["review"]["summary"]["used_hint"] is True

    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    assert game_reviews_repo.recent(conn)[0].used_hint is True
    conn.close()


def test_no_hint_after_the_review_is_over(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/show-answer", json={"step": STEP})
    assert client.post("/api/review/hint", json={"step": STEP}).status_code == 409


def test_no_hint_on_a_clean_game(client):
    start_review(client)
    assert client.post("/api/review/hint", json={"step": STEP}).status_code == 409


# -- explanations --------------------------------------------------------
def test_no_explanation_while_still_solving(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    assert client.post("/api/review/explain", json={"step": STEP}).status_code == 409


def test_no_explanation_for_a_clean_game(client):
    start_review(client)
    assert client.post("/api/review/explain", json={"step": STEP}).status_code == 409


def test_the_explanation_shows_both_lines(client, fake_engine_for_api):
    from chess_trainer import rules

    make_blunder(fake_engine_for_api, 2, "d2d4")
    target = positions()[2]
    after_best = rules.apply_move(target.fen_before, "d2d4").fen_after
    fake_engine_for_api.pvs[after_best] = ("e5d4", "f1c4")
    fake_engine_for_api.pvs[target.fen_after] = ("b8c6",)
    start_review(client)
    client.post("/api/review/show-answer", json={"step": STEP})

    payload = client.post("/api/review/explain", json={"step": STEP}).json()
    assert [m["label"] for m in payload["best"]["moves"]] == ["2.d4", "2...exd4", "3.Bc4"]
    assert [m["label"] for m in payload["mine"]["moves"]] == ["2.Nf3", "2...Nc6"]
    assert payload["mine"]["evaluation"]["cp"] == -900
    assert "Over this line you lose a pawn." in payload["best"]["notes"]
    assert payload["best"]["moves"][0]["fen_after"] == after_best


def test_the_board_is_oriented_to_my_colour(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    assert start_review(client)["orientation"] == "white"


def test_orientation_for_a_game_i_played_as_black(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 3, "g8f6", pgn=BLACK_PGN)
    payload = start_review(client, pgn=BLACK_PGN)
    assert payload["orientation"] == "black"
    assert payload["target"]["mover_is_white"] is False


def test_restarting_reuses_the_existing_review(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    calls = fake_engine_for_api.call_count
    client.post("/api/review/start", json={"step": STEP})
    assert fake_engine_for_api.call_count == calls


def test_restart_forces_a_fresh_analysis(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post(
        "/api/review/start", json={"step": STEP, "restart": True}
    ).json()
    assert payload["status"] in {"analysing", "ready"}


def test_the_depth_is_reported(client, config):
    assert start_review(client)["depth"] == config.engine_depth


def test_only_review_steps_are_accepted(client):
    client.post("/api/game/paste", json={"pgn": PGN})
    response = client.post("/api/review/start", json={"step": "cards"})
    assert response.status_code == 422
    assert "not a review step" in response.json()["detail"]


def test_the_play_step_is_not_a_review_step(client):
    client.post("/api/game/paste", json={"pgn": PGN})
    assert client.post("/api/review/start", json={"step": "play"}).status_code == 422


def test_only_the_review_step_runs_a_review(client):
    client.post("/api/game/paste", json={"pgn": PGN})
    response = client.post("/api/review/start", json={"step": "inaccuracy_cards"})
    assert response.status_code == 422


# -- state ---------------------------------------------------------------
def test_state_without_a_review_is_a_409(client):
    response = client.get(f"/api/review/{STEP}")
    assert response.status_code == 409
    assert "No review is running" in response.json()["detail"]


def test_state_rejects_a_non_review_step(client):
    assert client.get("/api/review/cards").status_code == 422


# -- attempts ------------------------------------------------------------
def test_a_wrong_attempt_is_reported_with_an_evaluation(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"}
    ).json()
    assert payload["correct"] is False
    assert payload["san"] == "a3"
    assert payload["attempts"] == 1
    assert payload["evaluation"]["text"]
    assert payload["review"]["finished"] is False


def test_the_eval_bar_updates_on_every_attempt(client, fake_engine_for_api):
    """Each wrong try must come back with its own evaluation."""
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    first = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"}
    ).json()
    second = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "h2", "to": "h4"}
    ).json()
    assert first["evaluation"]["fraction"] is not None
    assert second["evaluation"]["fraction"] is not None
    assert second["attempts"] == 2


def test_retries_are_unlimited(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    for _ in range(12):
        response = client.post(
            "/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"}
        )
        assert response.status_code == 200
    assert response.json()["attempts"] == 12


def test_the_correct_move_finishes_the_review(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"}
    ).json()
    assert payload["correct"] is True
    assert payload["review"]["finished"] is True
    assert payload["review"]["solved"] is True


def test_the_summary_appears_once_solved(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"})
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"}
    ).json()
    summary = payload["review"]["summary"]
    assert summary["found_an_inaccuracy"]
    assert summary["my_move_san"] == "Nf3"
    assert summary["best_move_san"] == "d4"
    assert summary["classification"] == "blunder"
    assert summary["attempts"] == 2
    assert summary["solved_first_try"] is False
    assert summary["eval_before"]["text"] == "0.00"
    assert summary["win_percent_drop"] > 30


def test_solving_first_try_is_recorded(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"}
    ).json()
    assert payload["review"]["summary"]["solved_first_try"] is True


def test_solving_completes_the_step_and_moves_the_streak(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"}
    ).json()
    assert payload["session"]["current"] == "cards"
    assert payload["streak"]["current"] == 1


def test_solving_writes_a_history_row(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"})
    client.post("/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"})

    from chess_trainer.db import game_reviews_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    rows = game_reviews_repo.recent(conn)
    assert len(rows) == 1
    assert rows[0].classification == "blunder"
    assert rows[0].my_move_san == "Nf3"
    assert rows[0].best_move_san == "d4"
    assert rows[0].attempts == 2
    assert rows[0].used_show_answer is False
    assert rows[0].first_inaccuracy_ply == 2
    conn.close()


def test_attempting_after_finishing_is_a_409(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"})
    response = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"}
    )
    assert response.status_code == 409
    assert "already finished" in response.json()["detail"]


def test_an_illegal_attempt_is_a_422(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    response = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "a1", "to": "a8"}
    )
    assert response.status_code == 422
    assert "not legal" in response.json()["detail"]


def test_attempting_on_a_clean_game_is_a_409(client):
    start_review(client)
    response = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "e2", "to": "e4"}
    )
    assert response.status_code == 409
    assert "no inaccuracy" in response.json()["detail"].lower()


def test_attempting_without_a_review_is_a_409(client):
    assert client.post(
        "/api/review/attempt", json={"step": STEP, "from": "e2", "to": "e4"}
    ).status_code == 409


# -- show answer ---------------------------------------------------------
def test_showing_the_answer_reveals_the_move(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post("/api/review/show-answer", json={"step": STEP}).json()
    assert payload["best_move_uci"] == "d2d4"
    assert payload["best_move_san"] == "d4"
    assert payload["evaluation"]["text"]


def test_showing_the_answer_finishes_the_review(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post("/api/review/show-answer", json={"step": STEP}).json()
    assert payload["review"]["finished"] is True
    assert payload["review"]["used_show_answer"] is True
    assert payload["review"]["solved"] is False
    assert payload["review"]["summary"]["used_show_answer"] is True


def test_showing_the_answer_completes_the_step(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    payload = client.post("/api/review/show-answer", json={"step": STEP}).json()
    assert payload["session"]["current"] == "cards"
    assert payload["streak"]["current"] == 1


def test_showing_the_answer_records_it_in_the_history(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/attempt", json={"step": STEP, "from": "a2", "to": "a3"})
    client.post("/api/review/show-answer", json={"step": STEP})

    from chess_trainer.db import game_reviews_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    row = game_reviews_repo.recent(conn)[0]
    assert row.used_show_answer is True
    assert row.attempts == 1
    conn.close()


def test_solving_then_revealing_writes_only_one_history_row(client, fake_engine_for_api):
    """Finishing twice must not double-count the streak or the history."""
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    client.post("/api/review/attempt", json={"step": STEP, "from": "d2", "to": "d4"})
    client.post("/api/review/show-answer", json={"step": STEP})

    from chess_trainer.db import game_reviews_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    assert game_reviews_repo.count(conn) == 1
    conn.close()
    assert client.get("/api/streak").json()["total_days"] == 1


def test_showing_the_answer_on_a_clean_game_is_a_409(client):
    start_review(client)
    assert client.post("/api/review/show-answer", json={"step": STEP}).status_code == 409


# -- acknowledge ---------------------------------------------------------
def test_acknowledging_a_clean_game_completes_the_step(client):
    start_review(client)
    payload = client.post("/api/review/acknowledge", json={"step": STEP}).json()
    assert payload["session"]["current"] == "cards"
    assert payload["streak"]["current"] == 1


def test_acknowledging_writes_an_empty_history_row(client):
    start_review(client)
    client.post("/api/review/acknowledge", json={"step": STEP})

    from chess_trainer.db import game_reviews_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    row = game_reviews_repo.recent(conn)[0]
    assert row.first_inaccuracy_ply is None
    assert not row.found_an_inaccuracy
    conn.close()


def test_acknowledging_an_unsolved_target_is_refused(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    response = client.post("/api/review/acknowledge", json={"step": STEP})
    assert response.status_code == 409
    assert "position to solve" in response.json()["detail"]


def test_acknowledging_twice_counts_once(client):
    start_review(client)
    client.post("/api/review/acknowledge", json={"step": STEP})
    client.post("/api/review/acknowledge", json={"step": STEP})

    from chess_trainer.db import game_reviews_repo
    from chess_trainer.db.connection import connect

    conn = connect(client.app.state.ctx.config.db_path)
    assert game_reviews_repo.count(conn) == 1
    conn.close()


# -- the real game -------------------------------------------------------
def test_the_real_chesscom_game_reviews(client, chesscom_pgn, fake_engine_for_api):
    target = from_parsed(parse_pgn(chesscom_pgn))[20]  # 11.f4, my 11th move
    fake_engine_for_api.results[target.fen_before] = Eval(cp=698)
    fake_engine_for_api.results[target.fen_after] = Eval(cp=-684)
    fake_engine_for_api.best_moves[target.fen_before] = "e1c1"

    client.post("/api/game/paste", json={"pgn": chesscom_pgn})
    client.post("/api/review/start", json={"step": STEP})
    payload = wait_until_ready(client)

    assert payload["target"]["move_label"] == "11.f4"
    assert len(payload["target"]["replay_ucis"]) == 20

    solved = client.post(
        "/api/review/attempt", json={"step": STEP, "from": "e1", "to": "c1"}
    ).json()
    assert solved["correct"]
    assert solved["san"] == "O-O-O"
    assert solved["review"]["summary"]["my_move_san"] == "f4"
    assert solved["review"]["summary"]["classification"] == "blunder"


# -- choosing which game to review --------------------------------------
def test_an_explicit_game_id_is_reviewed(client):
    """A pasted game must be reviewable even when an older dated game exists.

    `latest` orders by when a game was *played*, so an undated paste loses to a
    dated game; naming the game explicitly is how the paste fallback works.
    """
    dated = '[White "test-player"]\n[Black "dated"]\n[UTCDate "2025.01.15"]\n[UTCTime "12:00:00"]\n\n1. e4 e5 *\n'
    client.post("/api/game/paste", json={"pgn": dated})
    undated = client.post("/api/game/paste", json={"pgn": PGN}).json()["game"]
    assert undated["end_time"] is None

    without_id = client.post("/api/review/start", json={"step": STEP}).json()
    assert without_id["game"]["opponent"] == "dated"  # the dated game wins

    with_id = client.post(
        "/api/review/start",
        json={"step": STEP, "game_id": undated["id"], "restart": True},
    ).json()
    assert with_id["game"]["id"] == undated["id"]
    assert with_id["game"]["opponent"] == "rival"


def test_an_unknown_game_id_is_a_404(client):
    client.post("/api/game/paste", json={"pgn": PGN})
    response = client.post(
        "/api/review/start", json={"step": STEP, "game_id": "no-such-game"}
    )
    assert response.status_code == 404


def test_switching_games_replaces_the_review(client, fake_engine_for_api):
    make_blunder(fake_engine_for_api, 2, "d2d4")
    start_review(client)
    other = client.post(
        "/api/game/paste",
        json={"pgn": '[White "test-player"]\n[Black "other"]\n\n1. d4 d5 *\n'},
    ).json()["game"]
    payload = client.post(
        "/api/review/start", json={"step": STEP, "game_id": other["id"]}
    ).json()
    assert payload["game"]["opponent"] == "other"
