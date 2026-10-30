from __future__ import annotations

from chess_trainer.db import cards_repo, schedule_repo
from chess_trainer.db.cards_repo import STATUS_ACTIVE, STATUS_DEAD_END, CardRow

FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def row(n: int = 1, **overrides) -> CardRow:
    base = dict(
        epd=f"epd-{n}", fen=FEN, line_uci="e2e4", depth=1, side_to_move="black",
        given_move_uci="e2e4", given_move_san="e4", status=STATUS_ACTIVE,
        position_games=1000, queue_seq=n,
    )
    base.update(overrides)
    return CardRow(**base)


def test_empty_repository(conn):
    assert cards_repo.count(conn) == 0
    assert not cards_repo.has_any(conn)
    assert cards_repo.next_new_card(conn) is None
    assert cards_repo.max_queue_seq(conn) == 0


def test_insert_then_get(conn):
    created = cards_repo.insert(conn, row())
    assert created.id is not None
    assert cards_repo.get(conn, created.id).epd == "epd-1"
    assert cards_repo.get_by_epd(conn, "epd-1").id == created.id


def test_created_at_is_set(conn):
    assert cards_repo.insert(conn, row()).created_at is not None


def test_a_position_is_only_one_card(conn):
    first = cards_repo.insert(conn, row())
    second = cards_repo.insert(conn, row(line_uci="d2d4", queue_seq=2))
    assert second.id == first.id
    assert cards_repo.count(conn) == 1


def test_the_line_splits_back_into_moves(conn):
    created = cards_repo.insert(conn, row(line_uci="e2e4 c7c5", depth=2))
    assert created.ucis == ("e2e4", "c7c5")


def test_an_empty_line_gives_no_moves(conn):
    assert cards_repo.insert(conn, row(line_uci="")).ucis == ()


def test_the_opening_label_joins_eco_and_name(conn):
    created = cards_repo.insert(
        conn, row(opening_eco="B00", opening_name="King's Pawn Game")
    )
    assert created.opening_label == "B00 King's Pawn Game"


def test_the_opening_label_without_an_eco(conn):
    assert cards_repo.insert(conn, row(opening_name="Something")).opening_label == "Something"


def test_no_opening_means_no_label(conn):
    assert cards_repo.insert(conn, row()).opening_label is None


def test_max_queue_seq(conn):
    cards_repo.insert(conn, row(1, queue_seq=5))
    cards_repo.insert(conn, row(2, queue_seq=9))
    assert cards_repo.max_queue_seq(conn) == 9


# -- answers -------------------------------------------------------------
def test_a_new_card_needs_an_answer(conn):
    created = cards_repo.insert(conn, row())
    assert cards_repo.needs_answer(created)


def test_setting_the_answer(conn):
    created = cards_repo.insert(conn, row())
    updated = cards_repo.set_answer(
        conn, created.id, mode="frequency", answer_uci="c7c5", answer_san="c5"
    )
    assert updated.answer_uci == "c7c5"
    assert updated.answer_san == "c5"
    assert updated.mode == "frequency"
    assert not cards_repo.needs_answer(updated)


def test_setting_the_answer_records_a_tie(conn):
    created = cards_repo.insert(conn, row())
    updated = cards_repo.set_answer(
        conn, created.id, mode="frequency", answer_uci="c7c5",
        answer_san="c5", tied_ucis=("c7c5", "e7e5"),
    )
    assert set(updated.tied_ucis) == {"c7c5", "e7e5"}


def test_no_tie_stores_nothing(conn):
    created = cards_repo.insert(conn, row())
    updated = cards_repo.set_answer(
        conn, created.id, mode="frequency", answer_uci="c7c5", answer_san="c5"
    )
    assert updated.tied_ucis == ()


def test_setting_the_answer_can_add_the_opening(conn):
    created = cards_repo.insert(conn, row())
    updated = cards_repo.set_answer(
        conn, created.id, mode="frequency", answer_uci="c7c5", answer_san="c5",
        opening_eco="B20", opening_name="Sicilian Defense",
    )
    assert updated.opening_label == "B20 Sicilian Defense"


def test_setting_the_answer_keeps_an_existing_opening(conn):
    created = cards_repo.insert(conn, row(opening_eco="B00", opening_name="Keep me"))
    updated = cards_repo.set_answer(
        conn, created.id, mode="frequency", answer_uci="c7c5", answer_san="c5"
    )
    assert updated.opening_name == "Keep me"


def test_a_dead_end_needs_no_answer(conn):
    created = cards_repo.insert(conn, row(status=STATUS_DEAD_END))
    assert not cards_repo.needs_answer(created)


def test_marking_a_dead_end(conn):
    created = cards_repo.insert(conn, row())
    updated = cards_repo.mark_dead_end(conn, created.id, position_games=3)
    assert updated.is_dead_end
    assert updated.position_games == 3


# -- children ------------------------------------------------------------
def test_children_are_listed_in_queue_order(conn):
    parent = cards_repo.insert(conn, row(1))
    for n, seq in ((2, 20), (3, 10)):
        cards_repo.insert(conn, row(n, parent_card_id=parent.id, queue_seq=seq, depth=2))
    assert [c.queue_seq for c in cards_repo.children(conn, parent.id)] == [10, 20]


def test_dead_end_children_are_filtered(conn):
    parent = cards_repo.insert(conn, row(1))
    cards_repo.insert(conn, row(2, parent_card_id=parent.id, depth=2))
    cards_repo.insert(
        conn, row(3, parent_card_id=parent.id, depth=2, status=STATUS_DEAD_END)
    )
    dead = cards_repo.dead_end_children(conn, parent.id)
    assert len(dead) == 1
    assert dead[0].epd == "epd-3"


def test_deleting_a_parent_removes_its_children(conn):
    from chess_trainer.db.connection import transaction

    parent = cards_repo.insert(conn, row(1))
    cards_repo.insert(conn, row(2, parent_card_id=parent.id, depth=2))
    with transaction(conn):
        conn.execute("DELETE FROM cards WHERE id = ?", (parent.id,))
    assert cards_repo.count(conn) == 0


# -- expansion -----------------------------------------------------------
def test_a_new_card_is_not_expanded(conn):
    assert not cards_repo.insert(conn, row()).is_expanded


def test_marking_expanded(conn):
    created = cards_repo.insert(conn, row())
    cards_repo.mark_expanded(conn, created.id)
    assert cards_repo.get(conn, created.id).is_expanded


def test_marking_expanded_twice_keeps_the_first_time(conn):
    created = cards_repo.insert(conn, row())
    cards_repo.mark_expanded(conn, created.id)
    first = cards_repo.get(conn, created.id).expanded_at
    cards_repo.mark_expanded(conn, created.id)
    assert cards_repo.get(conn, created.id).expanded_at == first


# -- the new-card queue --------------------------------------------------
def test_the_next_new_card_is_breadth_first(conn):
    cards_repo.insert(conn, row(1, depth=2, queue_seq=1))
    cards_repo.insert(conn, row(2, depth=1, queue_seq=99))
    assert cards_repo.next_new_card(conn).epd == "epd-2"


def test_a_scheduled_card_is_no_longer_new(conn):
    from datetime import date

    created = cards_repo.insert(conn, row())
    assert cards_repo.count_new(conn) == 1
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=created.id, n=1, ef=2.5, interval_days=1, due_on=date(2026, 10, 30)
        ),
    )
    assert cards_repo.count_new(conn) == 0
    assert cards_repo.next_new_card(conn) is None


def test_dead_ends_are_not_new_cards(conn):
    cards_repo.insert(conn, row(status=STATUS_DEAD_END))
    assert cards_repo.count_new(conn) == 0
    assert cards_repo.next_new_card(conn) is None


def test_counting_by_status(conn):
    cards_repo.insert(conn, row(1))
    cards_repo.insert(conn, row(2, status=STATUS_DEAD_END))
    assert cards_repo.count(conn) == 2
    assert cards_repo.count(conn, STATUS_ACTIVE) == 1
    assert cards_repo.count(conn, STATUS_DEAD_END) == 1


def test_an_invalid_status_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        cards_repo.insert(conn, row(status="maybe"))


def test_an_invalid_side_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        cards_repo.insert(conn, row(side_to_move="purple"))


def test_an_invalid_mode_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        cards_repo.insert(conn, row(mode="vibes"))
