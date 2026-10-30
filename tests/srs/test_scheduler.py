"""The session queue: what comes next, and the no-double-scheduling rule."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from chess_trainer.db import cards_repo, review_log_repo, schedule_repo
from chess_trainer.srs.due import CardSource
from chess_trainer.srs.scheduler import CardQueue

TODAY = date(2026, 10, 30)


def make_card(conn, n: int, *, depth: int = 1, status: str = "active"):
    return cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=f"epd-{n}", fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            line_uci="e2e4", depth=depth, side_to_move="black",
            given_move_uci="e2e4", given_move_san="e4", status=status,
            position_games=100, queue_seq=n, mode="frequency",
            answer_uci="c7c5", answer_san="c5",
        ),
    )


def pass_card(queue, conn, card):
    return queue.record_answer(
        conn, card, attempts=1, used_show_answer=False, today=TODAY
    )


def fail_card(queue, conn, card):
    return queue.record_answer(
        conn, card, attempts=1, used_show_answer=True, today=TODAY
    )


# -- serving -------------------------------------------------------------
def test_an_empty_database_serves_nothing(conn):
    assert CardQueue().next_item(conn, TODAY) is None


def test_a_new_card_is_served(conn):
    make_card(conn, 1)
    item = CardQueue().next_item(conn, TODAY)
    assert item.source is CardSource.NEW
    assert item.card.id is not None


def test_new_cards_come_in_breadth_first_order(conn):
    make_card(conn, 2, depth=2)
    make_card(conn, 1, depth=1)
    item = CardQueue().next_item(conn, TODAY)
    assert item.card.depth == 1


def test_dead_ends_are_never_served(conn):
    make_card(conn, 1, status="dead_end")
    assert CardQueue().next_item(conn, TODAY) is None


def test_due_cards_come_before_new_ones(conn):
    new = make_card(conn, 2)
    old = make_card(conn, 1)
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=old.id, n=1, ef=2.5, interval_days=1, due_on=TODAY
        ),
    )
    item = CardQueue().next_item(conn, TODAY)
    assert item.source is CardSource.DUE
    assert item.card.id == old.id
    assert item.card.id != new.id


def test_the_oldest_due_card_comes_first(conn):
    first = make_card(conn, 1)
    second = make_card(conn, 2)
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=first.id, n=1, ef=2.5, interval_days=1, due_on=TODAY
        ),
    )
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=second.id, n=1, ef=2.5, interval_days=1,
            due_on=TODAY - timedelta(days=5),
        ),
    )
    assert CardQueue().next_item(conn, TODAY).card.id == second.id


def test_a_card_due_in_the_future_is_not_served(conn):
    card = make_card(conn, 1)
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=card.id, n=1, ef=2.5, interval_days=10,
            due_on=TODAY + timedelta(days=10),
        ),
    )
    assert CardQueue().next_item(conn, TODAY) is None


def test_there_is_no_daily_limit(conn):
    """Twenty new cards can all be answered in one session."""
    for n in range(1, 21):
        make_card(conn, n)
    queue = CardQueue()
    answered = 0
    for _ in range(20):
        item = queue.next_item(conn, TODAY)
        assert item is not None
        queue.mark_served()
        pass_card(queue, conn, item.card)
        answered += 1
    assert answered == 20


# -- answering -----------------------------------------------------------
def test_passing_a_new_card_schedules_it(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    outcome = pass_card(queue, conn, card)
    assert outcome.passed
    assert outcome.was_new
    assert outcome.rescheduled
    assert outcome.interval_days == 1
    assert outcome.due_on == TODAY + timedelta(days=1)
    assert schedule_repo.get(conn, card.id) is not None


def test_a_first_try_pass_grades_four(conn):
    card = make_card(conn, 1)
    outcome = CardQueue().record_answer(
        conn, card, attempts=1, used_show_answer=False, today=TODAY
    )
    assert outcome.quality == 4


def test_a_retry_pass_grades_three(conn):
    card = make_card(conn, 1)
    outcome = CardQueue().record_answer(
        conn, card, attempts=3, used_show_answer=False, today=TODAY
    )
    assert outcome.quality == 3
    assert outcome.passed


def test_revealing_the_answer_fails_the_card(conn):
    card = make_card(conn, 1)
    outcome = fail_card(CardQueue(), conn, card)
    assert outcome.quality == 1
    assert not outcome.passed
    assert outcome.requeued


def test_answering_is_logged(conn):
    card = make_card(conn, 1)
    pass_card(CardQueue(), conn, card)
    rows = review_log_repo.for_card(conn, card.id)
    assert len(rows) == 1
    assert rows[0].quality == 4
    assert rows[0].was_new


def test_the_log_records_the_resulting_schedule(conn):
    card = make_card(conn, 1)
    pass_card(CardQueue(), conn, card)
    row = review_log_repo.for_card(conn, card.id)[0]
    assert row.interval_days == 1
    assert row.ef is not None


def test_reps_and_lapses_are_counted(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    fail_card(queue, conn, card)
    schedule = schedule_repo.get(conn, card.id)
    assert schedule.reps == 1
    assert schedule.lapses == 1


def test_a_second_session_advances_the_schedule(conn):
    card = make_card(conn, 1)
    pass_card(CardQueue(), conn, card)
    later = CardQueue()  # a fresh session
    outcome = pass_card(later, conn, cards_repo.get(conn, card.id))
    assert outcome.interval_days == 6
    assert not outcome.was_new
    assert schedule_repo.get(conn, card.id).reps == 2


# -- the requeue ---------------------------------------------------------
def test_a_failed_card_is_requeued(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    fail_card(queue, conn, card)
    assert queue.relearning_ids == [card.id]


def test_a_failed_card_waits_for_the_gap(conn):
    card = make_card(conn, 1)
    for n in range(2, 8):
        make_card(conn, n)
    queue = CardQueue()
    queue.mark_served()
    fail_card(queue, conn, card)

    served = []
    for _ in range(5):
        item = queue.next_item(conn, TODAY)
        served.append(item.source)
        queue.mark_served()
        if item.card.id != card.id:
            pass_card(queue, conn, item.card)
    assert served[0] is CardSource.NEW
    assert CardSource.RELEARN in served


def test_a_failed_card_comes_back_even_with_nothing_else_left(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    queue.mark_served()
    fail_card(queue, conn, card)
    item = queue.next_item(conn, TODAY)
    assert item is not None
    assert item.source is CardSource.RELEARN
    assert item.card.id == card.id


def test_passing_a_requeued_card_clears_it(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    fail_card(queue, conn, card)
    pass_card(queue, conn, card)
    assert queue.relearning_ids == []


def test_a_requeued_card_is_not_rescheduled_twice(conn):
    """The spec: a failed card reappears but is only rescheduled once."""
    card = make_card(conn, 1)
    queue = CardQueue()
    first = fail_card(queue, conn, card)
    assert first.rescheduled
    before = schedule_repo.get(conn, card.id)

    second = pass_card(queue, conn, card)
    assert not second.rescheduled
    assert second.result is None

    after = schedule_repo.get(conn, card.id)
    assert (after.n, after.ef, after.interval_days, after.due_on) == (
        before.n,
        before.ef,
        before.interval_days,
        before.due_on,
    )
    assert after.reps == 1


def test_the_retry_is_still_logged(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    fail_card(queue, conn, card)
    pass_card(queue, conn, card)
    assert len(review_log_repo.for_card(conn, card.id)) == 2


def test_a_retry_that_fails_again_stays_requeued(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    fail_card(queue, conn, card)
    fail_card(queue, conn, card)
    assert queue.relearning_ids == [card.id]


def test_a_fresh_session_reschedules_again(conn):
    card = make_card(conn, 1)
    first = CardQueue()
    fail_card(first, conn, card)
    second = CardQueue()
    outcome = pass_card(second, conn, cards_repo.get(conn, card.id))
    assert outcome.rescheduled
    assert schedule_repo.get(conn, card.id).reps == 2


def test_reset_clears_the_session_state(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    queue.mark_served()
    fail_card(queue, conn, card)
    queue.reset()
    assert queue.relearning_ids == []
    assert queue.served == 0


# -- counts --------------------------------------------------------------
def test_counts_report_due_new_and_relearning(conn):
    new_card = make_card(conn, 1)
    due_card = make_card(conn, 2)
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=due_card.id, n=1, ef=2.5, interval_days=1, due_on=TODAY
        ),
    )
    queue = CardQueue()
    counts = queue.counts(conn, TODAY)
    assert counts.due == 1
    assert counts.new == 1
    assert counts.relearning == 0
    assert counts.total_waiting == 2

    fail_card(queue, conn, new_card)
    assert queue.counts(conn, TODAY).relearning == 1


def test_an_answered_card_is_no_longer_new(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    assert queue.counts(conn, TODAY).new == 1
    pass_card(queue, conn, card)
    assert queue.counts(conn, TODAY).new == 0


# -- lapses keep the ladder position (persisted path) --------------------
def test_a_lapse_does_not_restart_the_ladder_across_sessions(conn):
    """The rule end to end: fail a mature card, then pass it tomorrow."""
    card = make_card(conn, 1)
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=card.id, n=4, ef=2.5, interval_days=38, due_on=TODAY, reps=4
        ),
    )

    # Today: the answer is revealed, so the card lapses.
    lapse = fail_card(CardQueue(), conn, cards_repo.get(conn, card.id))
    assert lapse.interval_days == 19  # halved, not reset
    after_lapse = schedule_repo.get(conn, card.id)
    assert after_lapse.n == 4  # the ladder position survived
    assert after_lapse.ef == pytest.approx(1.96)

    # A later session: it is answered correctly and grows from the halved value.
    tomorrow = TODAY + timedelta(days=1)
    recovery = CardQueue().record_answer(
        conn, cards_repo.get(conn, card.id), attempts=1,
        used_show_answer=False, today=tomorrow,
    )
    assert recovery.interval_days == 37  # round(19 * 1.96), not 1
    assert schedule_repo.get(conn, card.id).n == 5


def test_a_never_passed_card_stays_at_one_day_after_a_lapse(conn):
    card = make_card(conn, 1)
    queue = CardQueue()
    lapse = fail_card(queue, conn, card)
    assert lapse.interval_days == 1
    assert schedule_repo.get(conn, card.id).n == 0

    tomorrow = TODAY + timedelta(days=1)
    recovery = CardQueue().record_answer(
        conn, cards_repo.get(conn, card.id), attempts=1,
        used_show_answer=False, today=tomorrow,
    )
    assert recovery.interval_days == 1
    assert schedule_repo.get(conn, card.id).n == 1


def test_lapses_are_still_counted_even_though_n_survives(conn):
    card = make_card(conn, 1)
    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=card.id, n=3, ef=2.5, interval_days=15, due_on=TODAY
        ),
    )
    fail_card(CardQueue(), conn, cards_repo.get(conn, card.id))
    stored = schedule_repo.get(conn, card.id)
    assert stored.lapses == 1
    assert stored.n == 3
