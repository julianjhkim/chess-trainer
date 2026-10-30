from __future__ import annotations

from datetime import date, timedelta

from chess_trainer.db import cards_repo, schedule_repo
from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.schedule_repo import ScheduleRow

TODAY = date(2026, 10, 30)


def a_card(conn, n: int = 1, *, depth: int = 1, status: str = "active"):
    return cards_repo.insert(
        conn,
        CardRow(
            epd=f"epd-{n}", fen="f", line_uci="e2e4", depth=depth,
            side_to_move="black", given_move_uci="e2e4", given_move_san="e4",
            status=status, position_games=100, queue_seq=n,
        ),
    )


def schedule(card_id: int, due_on: date = TODAY, **overrides) -> ScheduleRow:
    base = dict(card_id=card_id, n=1, ef=2.5, interval_days=1, due_on=due_on)
    base.update(overrides)
    return ScheduleRow(**base)


def test_empty_repository(conn):
    assert schedule_repo.get(conn, 1) is None
    assert schedule_repo.count(conn) == 0
    assert schedule_repo.count_due(conn, TODAY) == 0
    assert schedule_repo.due_cards(conn, TODAY) == []
    assert schedule_repo.next_due(conn, TODAY) is None


def test_upsert_then_get(conn):
    card = a_card(conn)
    stored = schedule_repo.upsert(conn, schedule(card.id, n=3, ef=2.1, interval_days=15))
    assert stored.n == 3
    assert stored.ef == 2.1
    assert stored.interval_days == 15
    assert stored.due_on == TODAY


def test_upsert_replaces(conn):
    card = a_card(conn)
    schedule_repo.upsert(conn, schedule(card.id, n=1))
    schedule_repo.upsert(conn, schedule(card.id, n=5))
    assert schedule_repo.count(conn) == 1
    assert schedule_repo.get(conn, card.id).n == 5


def test_reps_and_lapses_round_trip(conn):
    card = a_card(conn)
    stored = schedule_repo.upsert(conn, schedule(card.id, reps=7, lapses=2))
    assert (stored.reps, stored.lapses) == (7, 2)


def test_last_reviewed_round_trips(conn):
    card = a_card(conn)
    stored = schedule_repo.upsert(conn, schedule(card.id, last_reviewed_on=TODAY))
    assert stored.last_reviewed_on == TODAY


def test_last_reviewed_may_be_absent(conn):
    card = a_card(conn)
    assert schedule_repo.upsert(conn, schedule(card.id)).last_reviewed_on is None


def test_is_due(conn):
    card = a_card(conn)
    stored = schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY))
    assert stored.is_due(TODAY)
    assert stored.is_due(TODAY + timedelta(days=1))
    assert not stored.is_due(TODAY - timedelta(days=1))


# -- due selection -------------------------------------------------------
def test_a_card_due_today_is_returned(conn):
    card = a_card(conn)
    schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY))
    found = schedule_repo.due_cards(conn, TODAY)
    assert len(found) == 1
    assert found[0][0].id == card.id
    assert found[0][1].card_id == card.id


def test_an_overdue_card_is_returned(conn):
    card = a_card(conn)
    schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY - timedelta(days=30)))
    assert schedule_repo.count_due(conn, TODAY) == 1


def test_a_future_card_is_not_returned(conn):
    card = a_card(conn)
    schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY + timedelta(days=1)))
    assert schedule_repo.due_cards(conn, TODAY) == []


def test_due_cards_are_oldest_first(conn):
    for n, offset in ((1, 0), (2, -10), (3, -5)):
        card = a_card(conn, n)
        schedule_repo.upsert(
            conn, schedule(card.id, due_on=TODAY + timedelta(days=offset))
        )
    assert [c.epd for c, _ in schedule_repo.due_cards(conn, TODAY)] == [
        "epd-2",
        "epd-3",
        "epd-1",
    ]


def test_ties_fall_back_to_breadth_first(conn):
    deep = a_card(conn, 1, depth=3)
    shallow = a_card(conn, 2, depth=1)
    for card in (deep, shallow):
        schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY))
    assert [c.id for c, _ in schedule_repo.due_cards(conn, TODAY)] == [
        shallow.id,
        deep.id,
    ]


def test_next_due_returns_the_first(conn):
    for n, offset in ((1, 0), (2, -10)):
        card = a_card(conn, n)
        schedule_repo.upsert(
            conn, schedule(card.id, due_on=TODAY + timedelta(days=offset))
        )
    card, _ = schedule_repo.next_due(conn, TODAY)
    assert card.epd == "epd-2"


def test_the_limit_is_respected(conn):
    for n in range(1, 6):
        card = a_card(conn, n)
        schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY))
    assert len(schedule_repo.due_cards(conn, TODAY, limit=2)) == 2


def test_dead_ends_are_never_due(conn):
    card = a_card(conn, status="dead_end")
    schedule_repo.upsert(conn, schedule(card.id, due_on=TODAY))
    assert schedule_repo.due_cards(conn, TODAY) == []
    assert schedule_repo.count_due(conn, TODAY) == 0


def test_deleting_a_card_removes_its_schedule(conn):
    from chess_trainer.db.connection import transaction

    card = a_card(conn)
    schedule_repo.upsert(conn, schedule(card.id))
    with transaction(conn):
        conn.execute("DELETE FROM cards WHERE id = ?", (card.id,))
    assert schedule_repo.count(conn) == 0


def test_the_card_and_schedule_both_come_back_whole(conn):
    """Both halves are built from one result row, so both must be complete."""
    card = a_card(conn)
    schedule_repo.upsert(
        conn, schedule(card.id, n=4, ef=1.9, interval_days=38, reps=5, lapses=1)
    )
    stored_card, stored_schedule = schedule_repo.due_cards(conn, TODAY)[0]
    assert stored_card.epd == "epd-1"
    assert stored_card.given_move_san == "e4"
    assert stored_schedule.card_id == card.id
    assert (stored_schedule.n, stored_schedule.ef, stored_schedule.interval_days) == (
        4,
        1.9,
        38,
    )
    assert (stored_schedule.reps, stored_schedule.lapses) == (5, 1)
