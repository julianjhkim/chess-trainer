from __future__ import annotations

from datetime import date

from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.srs import due
from chess_trainer.srs.due import CardSource, QueueItem, Requeued

TODAY = date(2026, 10, 30)


def card(card_id: int, depth: int = 1, seq: int = 1) -> CardRow:
    return CardRow(
        id=card_id, epd=f"e{card_id}", fen="f", line_uci="e2e4", depth=depth,
        side_to_move="black", given_move_uci="e2e4", given_move_san="e4",
        status="active", position_games=100, queue_seq=seq,
    )


def schedule(card_id: int, due_on: date) -> ScheduleRow:
    return ScheduleRow(
        card_id=card_id, n=1, ef=2.5, interval_days=1, due_on=due_on
    )


def test_the_requeue_gap_is_a_few_cards():
    assert due.REQUEUE_GAP >= 1


def test_a_card_due_today_is_due():
    assert due.is_due(schedule(1, TODAY), TODAY)


def test_an_overdue_card_is_due():
    assert due.is_due(schedule(1, date(2026, 1, 1)), TODAY)


def test_a_future_card_is_not_due():
    assert not due.is_due(schedule(1, date(2027, 1, 1)), TODAY)


def test_due_cards_are_ordered_oldest_first():
    entries = [
        (card(1), schedule(1, date(2026, 10, 29))),
        (card(2), schedule(2, date(2026, 10, 1))),
        (card(3), schedule(3, date(2026, 10, 15))),
    ]
    assert [c.id for c, _ in due.order_due(entries)] == [2, 3, 1]


def test_due_ties_fall_back_to_breadth_first_order():
    entries = [
        (card(1, depth=2, seq=50), schedule(1, TODAY)),
        (card(2, depth=1, seq=99), schedule(2, TODAY)),
    ]
    assert [c.id for c, _ in due.order_due(entries)] == [2, 1]


def test_ordering_an_empty_list():
    assert due.order_due([]) == []


# -- requeue -------------------------------------------------------------
def test_a_requeued_card_is_not_eligible_before_the_gap():
    waiting = [Requeued(card_id=1, eligible_at=5)]
    assert due.eligible_requeue(waiting, served=3) is None


def test_a_requeued_card_becomes_eligible_after_the_gap():
    waiting = [Requeued(card_id=1, eligible_at=5)]
    assert due.eligible_requeue(waiting, served=5).card_id == 1


def test_the_oldest_eligible_requeue_comes_first():
    waiting = [Requeued(card_id=1, eligible_at=2), Requeued(card_id=2, eligible_at=1)]
    assert due.eligible_requeue(waiting, served=9).card_id == 1


def test_no_requeue_means_none():
    assert due.eligible_requeue([], served=100) is None


def test_forced_requeue_ignores_the_gap():
    """Nothing else left to show, so a failed card must come anyway."""
    waiting = [Requeued(card_id=7, eligible_at=999)]
    assert due.forced_requeue(waiting).card_id == 7


def test_forced_requeue_of_nothing_is_none():
    assert due.forced_requeue([]) is None


def test_schedule_requeue_adds_the_gap():
    assert due.schedule_requeue(served=4, gap=3) == 7


# -- queue items ---------------------------------------------------------
def test_a_new_item_knows_it_is_new():
    assert QueueItem(card=card(1), source=CardSource.NEW).is_new


def test_a_due_item_is_not_new():
    assert not QueueItem(card=card(1), source=CardSource.DUE).is_new


def test_a_relearn_item_is_not_new():
    assert not QueueItem(card=card(1), source=CardSource.RELEARN).is_new


def test_the_sources_are_stable_strings():
    assert [s.value for s in CardSource] == ["due", "new", "relearn"]
