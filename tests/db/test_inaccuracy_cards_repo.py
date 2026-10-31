from __future__ import annotations

from datetime import date

import pytest

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard, InaccuracyReview
from chess_trainer.db.schedule_repo import ScheduleRow

FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
EPD = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"


def a_card(**overrides) -> InaccuracyCard:
    base = dict(
        epd=EPD, fen=FEN, ply=2, move_number=2, my_colour="white",
        my_move_uci="g1f3", my_move_san="Nf3", best_move_uci="d2d4", best_move_san="d4",
        classification="mistake", depth=20, last_move_uci="e7e5", win_percent_drop=21.0,
    )
    base.update(overrides)
    return InaccuracyCard(**base)


def test_a_card_round_trips(conn):
    stored = repo.insert(conn, a_card())
    assert stored.id is not None
    assert repo.get(conn, stored.id) == stored
    assert repo.get_by_epd(conn, EPD) == stored
    assert stored.move_label == "2.Nf3"


def test_one_card_per_position(conn):
    import sqlite3

    repo.insert(conn, a_card())
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert(conn, a_card())


def test_black_move_labels_use_three_dots(conn):
    assert a_card(my_colour="black", my_move_san="Nc6").move_label == "2...Nc6"


def test_schedule_and_due_queries(conn):
    card = repo.insert(conn, a_card())
    repo.upsert_schedule(conn, ScheduleRow(card_id=card.id, n=1, ef=2.5, interval_days=1, due_on=date(2026, 11, 1)))
    assert repo.count_due(conn, date(2026, 10, 31)) == 0
    assert repo.count_due(conn, date(2026, 11, 1)) == 1
    assert repo.next_due_on(conn, date(2026, 10, 31)) == date(2026, 11, 1)
    assert repo.next_due_on(conn, date(2026, 11, 1)) is None
    assert [c.id for c, _ in repo.due_cards(conn, date(2026, 11, 2))] == [card.id]


def test_reviews_are_logged(conn):
    card = repo.insert(conn, a_card())
    repo.record_review(conn, InaccuracyReview(card_id=card.id, reviewed_on=date(2026, 10, 31), quality=2, attempts=3))
    (row,) = repo.recent_reviews(conn)
    assert (row.quality, row.attempts, row.used_hint) == (2, 3, False)
