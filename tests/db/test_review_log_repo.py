from __future__ import annotations

from datetime import date

from chess_trainer.db import cards_repo, review_log_repo
from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.review_log_repo import CardReview

TODAY = date(2026, 10, 30)


def a_card(conn, n: int = 1):
    return cards_repo.insert(
        conn,
        CardRow(
            epd=f"epd-{n}", fen="f", line_uci="e2e4", depth=1, side_to_move="black",
            given_move_uci="e2e4", given_move_san="e4", status="active",
            position_games=100, queue_seq=n,
        ),
    )


def review(card_id: int, **overrides) -> CardReview:
    base = dict(
        card_id=card_id, reviewed_on=TODAY, quality=4, attempts=1,
        used_show_answer=False, was_new=True, interval_days=1, ef=2.5,
    )
    base.update(overrides)
    return CardReview(**base)


def test_empty_repository(conn):
    assert review_log_repo.count(conn) == 0
    assert review_log_repo.recent(conn) == []
    assert review_log_repo.for_card(conn, 1) == []
    assert review_log_repo.answered_on(conn, TODAY) == 0


def test_record_assigns_an_id(conn):
    card = a_card(conn)
    stored = review_log_repo.record(conn, review(card.id))
    assert stored.id is not None
    assert review_log_repo.count(conn) == 1


def test_everything_round_trips(conn):
    card = a_card(conn)
    stored = review_log_repo.record(
        conn,
        review(card.id, quality=3, attempts=4, used_show_answer=True,
               was_new=False, interval_days=19, ef=1.96),
    )
    assert stored.quality == 3
    assert stored.attempts == 4
    assert stored.used_show_answer is True
    assert stored.was_new is False
    assert stored.interval_days == 19
    assert stored.ef == 1.96
    assert stored.reviewed_on == TODAY


def test_reviewed_at_is_set(conn):
    card = a_card(conn)
    assert review_log_repo.record(conn, review(card.id)).reviewed_at.endswith("+00:00")


def test_the_passed_flag(conn):
    card = a_card(conn)
    assert review_log_repo.record(conn, review(card.id, quality=4)).passed
    assert review_log_repo.record(conn, review(card.id, quality=3)).passed
    assert not review_log_repo.record(conn, review(card.id, quality=1)).passed


def test_several_answers_to_one_card_are_all_kept(conn):
    card = a_card(conn)
    review_log_repo.record(conn, review(card.id, quality=1))
    review_log_repo.record(conn, review(card.id, quality=4))
    assert len(review_log_repo.for_card(conn, card.id)) == 2


def test_for_card_filters(conn):
    first = a_card(conn, 1)
    second = a_card(conn, 2)
    review_log_repo.record(conn, review(first.id))
    review_log_repo.record(conn, review(second.id))
    assert len(review_log_repo.for_card(conn, first.id)) == 1


def test_recent_is_newest_first(conn):
    card = a_card(conn)
    first = review_log_repo.record(conn, review(card.id, quality=1))
    second = review_log_repo.record(conn, review(card.id, quality=4))
    assert [r.id for r in review_log_repo.recent(conn)] == [second.id, first.id]


def test_recent_respects_the_limit(conn):
    card = a_card(conn)
    for _ in range(5):
        review_log_repo.record(conn, review(card.id))
    assert len(review_log_repo.recent(conn, limit=2)) == 2


def test_answered_on_counts_a_day(conn):
    card = a_card(conn)
    review_log_repo.record(conn, review(card.id))
    review_log_repo.record(conn, review(card.id))
    review_log_repo.record(conn, review(card.id, reviewed_on=date(2026, 10, 29)))
    assert review_log_repo.answered_on(conn, TODAY) == 2
    assert review_log_repo.answered_on(conn, date(2026, 10, 29)) == 1


def test_an_unknown_card_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        review_log_repo.record(conn, review(999))


def test_deleting_a_card_removes_its_log(conn):
    from chess_trainer.db.connection import transaction

    card = a_card(conn)
    review_log_repo.record(conn, review(card.id))
    with transaction(conn):
        conn.execute("DELETE FROM cards WHERE id = ?", (card.id,))
    assert review_log_repo.count(conn) == 0
