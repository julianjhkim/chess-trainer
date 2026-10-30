from __future__ import annotations

from datetime import date

from chess_trainer.db import game_reviews_repo as repo
from chess_trainer.db import games_repo
from chess_trainer.db.game_reviews_repo import GameReview
from chess_trainer.engine.eval_types import Eval

DAY = date(2026, 10, 30)


def a_game(conn, game_id="g1"):
    return games_repo.upsert(
        conn, games_repo.StoredGame(id=game_id, pgn="1. e4 e5 *", my_color="white")
    )


def full_review(game_id="g1", **overrides) -> GameReview:
    base = dict(
        game_id=game_id,
        depth=20,
        reviewed_on=DAY,
        first_inaccuracy_ply=20,
        my_move_uci="f2f4",
        my_move_san="f4",
        classification="blunder",
        best_move_uci="e1c1",
        best_move_san="O-O-O",
        eval_before=Eval(cp=698),
        eval_after=Eval(cp=-684),
        win_percent_drop=85.4,
        attempts=3,
        used_show_answer=True,
    )
    base.update(overrides)
    return GameReview(**base)


def test_empty_repository(conn):
    assert repo.count(conn) == 0
    assert repo.recent(conn) == []
    assert repo.for_game(conn, "g1") == []
    assert repo.get(conn, 1) is None


def test_record_assigns_an_id(conn):
    a_game(conn)
    stored = repo.record(conn, full_review())
    assert stored.id is not None
    assert repo.count(conn) == 1


def test_all_the_fields_round_trip(conn):
    a_game(conn)
    stored = repo.record(conn, full_review())
    assert stored.game_id == "g1"
    assert stored.reviewed_on == DAY
    assert stored.first_inaccuracy_ply == 20
    assert stored.my_move_san == "f4"
    assert stored.my_move_uci == "f2f4"
    assert stored.classification == "blunder"
    assert stored.best_move_san == "O-O-O"
    assert stored.eval_before == Eval(cp=698)
    assert stored.eval_after == Eval(cp=-684)
    assert stored.win_percent_drop == 85.4
    assert stored.attempts == 3
    assert stored.used_show_answer is True
    assert stored.depth == 20


def test_reviewed_at_is_set_automatically(conn):
    a_game(conn)
    stored = repo.record(conn, full_review())
    assert stored.reviewed_at and stored.reviewed_at.endswith("+00:00")


def test_mate_evaluations_round_trip(conn):
    a_game(conn)
    stored = repo.record(
        conn, full_review(eval_before=Eval(mate=3), eval_after=Eval(mate=-1))
    )
    assert stored.eval_before == Eval(mate=3)
    assert stored.eval_after == Eval(mate=-1)


def test_a_clean_game_review_is_stored_with_empty_move_columns(conn):
    a_game(conn)
    stored = repo.record(
        conn, GameReview(game_id="g1", depth=20, reviewed_on=DAY, attempts=0)
    )
    assert stored.first_inaccuracy_ply is None
    assert stored.my_move_san is None
    assert stored.eval_before is None
    assert not stored.found_an_inaccuracy


def test_found_an_inaccuracy_flag(conn):
    a_game(conn)
    assert repo.record(conn, full_review()).found_an_inaccuracy


def test_several_reviews_of_one_game_are_all_kept(conn):
    a_game(conn)
    repo.record(conn, full_review(attempts=1))
    repo.record(conn, full_review(attempts=5))
    assert repo.count(conn) == 2
    assert len(repo.for_game(conn, "g1")) == 2


def test_for_game_filters_by_game(conn):
    a_game(conn, "g1")
    a_game(conn, "g2")
    repo.record(conn, full_review("g1"))
    repo.record(conn, full_review("g2"))
    assert len(repo.for_game(conn, "g1")) == 1


def test_recent_respects_the_limit(conn):
    a_game(conn)
    for _ in range(5):
        repo.record(conn, full_review())
    assert len(repo.recent(conn, limit=2)) == 2


def test_recent_is_newest_first(conn):
    a_game(conn)
    first = repo.record(conn, full_review(attempts=1))
    second = repo.record(conn, full_review(attempts=2))
    assert [r.id for r in repo.recent(conn)] == [second.id, first.id]


def test_get_by_id(conn):
    a_game(conn)
    stored = repo.record(conn, full_review())
    assert repo.get(conn, stored.id).attempts == 3


def test_a_review_of_an_unknown_game_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        repo.record(conn, full_review("no-such-game"))


def test_deleting_a_game_removes_its_reviews(conn):
    from chess_trainer.db.connection import transaction

    a_game(conn)
    repo.record(conn, full_review())
    with transaction(conn):
        conn.execute("DELETE FROM games WHERE id = 'g1'")
    assert repo.count(conn) == 0


def test_a_hint_survives_the_round_trip(conn):
    a_game(conn)
    stored = repo.record(conn, full_review(used_hint=True))
    assert stored.used_hint is True


def test_no_hint_is_the_default(conn):
    a_game(conn)
    assert repo.record(conn, full_review()).used_hint is False
