from __future__ import annotations

from datetime import date, timedelta

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.inaccuracies.deck import InaccuracyDeck, add_card
from chess_trainer.pgn.positions import walk
from chess_trainer.srs.due import CardSource

TODAY = date(2026, 10, 31)
TOMORROW = TODAY + timedelta(days=1)
LINE = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]


def card(ply: int = 2) -> InaccuracyCard:
    position = walk(LINE)[ply]
    import chess

    return InaccuracyCard(
        epd=chess.Board(position.fen_before).epd(),
        fen=position.fen_before,
        ply=ply,
        move_number=position.move_number,
        my_colour="white" if position.mover_is_white else "black",
        my_move_uci=position.uci,
        my_move_san=position.san,
        best_move_uci="d2d4" if ply == 2 else position.uci,
        best_move_san="d4",
        classification="inaccuracy",
        depth=20,
    )


def make_due(conn, card_id: int, on: date = TODAY) -> None:
    schedule = repo.get_schedule(conn, card_id)
    repo.upsert_schedule(
        conn,
        ScheduleRow(
            card_id=card_id,
            n=schedule.n,
            ef=schedule.ef,
            interval_days=schedule.interval_days,
            due_on=on,
        ),
    )


# -- adding ------------------------------------------------------------------
def test_a_new_card_is_due_tomorrow_as_if_passed_once(conn):
    added = add_card(conn, card(), today=TODAY)
    assert added.created
    assert added.due_on == TOMORROW
    schedule = repo.get_schedule(conn, added.card.id)
    assert (schedule.n, schedule.interval_days, schedule.ef) == (1, 1, 2.5)


def test_a_new_card_is_not_due_today(conn):
    add_card(conn, card(), today=TODAY)
    assert InaccuracyDeck().next_item(conn, TODAY) is None


def test_the_same_position_again_brings_the_card_back(conn):
    first = add_card(conn, card(), today=TODAY)
    make_due(conn, first.card.id, on=TODAY + timedelta(days=30))
    again = add_card(conn, card(), today=TODAY)
    assert not again.created
    assert again.card.id == first.card.id
    assert again.due_on == TOMORROW
    assert repo.count(conn) == 1


def test_a_repeat_never_pushes_a_card_later(conn):
    first = add_card(conn, card(), today=TODAY)
    make_due(conn, first.card.id, on=TODAY)
    assert add_card(conn, card(), today=TODAY).due_on == TODAY


# -- serving and answering ---------------------------------------------------
def test_due_cards_are_served_oldest_first(conn):
    a = add_card(conn, card(2), today=TODAY).card
    b = add_card(conn, card(4), today=TODAY).card
    make_due(conn, b.id, on=TODAY - timedelta(days=3))
    make_due(conn, a.id, on=TODAY)
    item = InaccuracyDeck().next_item(conn, TODAY)
    assert item.card.id == b.id
    assert item.source is CardSource.DUE


def test_a_first_try_pass_climbs_the_ladder(conn):
    c = add_card(conn, card(), today=TODAY).card
    make_due(conn, c.id)
    answer = InaccuracyDeck().record_answer(
        conn, c, attempts=1, used_show_answer=False, used_hint=False, today=TODAY
    )
    assert answer.passed and answer.quality == 4
    assert answer.result.interval_days == 6


def test_a_hint_caps_the_grade_at_three(conn):
    c = add_card(conn, card(), today=TODAY).card
    answer = InaccuracyDeck().record_answer(
        conn, c, attempts=1, used_show_answer=False, used_hint=True, today=TODAY
    )
    assert answer.quality == 3
    assert answer.passed
    assert answer.description == "right with a hint"


def test_a_third_try_fails_and_comes_back_this_session(conn):
    deck = InaccuracyDeck(gap=0)
    c = add_card(conn, card(), today=TODAY).card
    make_due(conn, c.id)
    deck.mark_served()
    answer = deck.record_answer(
        conn, c, attempts=3, used_show_answer=False, used_hint=False, today=TODAY
    )
    assert not answer.passed and answer.requeued
    item = deck.next_item(conn, TODAY)
    assert item.card.id == c.id
    assert item.source is CardSource.RELEARN


def test_the_retry_in_the_same_session_does_not_reschedule(conn):
    deck = InaccuracyDeck(gap=0)
    c = add_card(conn, card(), today=TODAY).card
    first = deck.record_answer(
        conn, c, attempts=1, used_show_answer=True, used_hint=False, today=TODAY
    )
    second = deck.record_answer(
        conn, c, attempts=1, used_show_answer=False, used_hint=False, today=TODAY
    )
    assert first.result is not None
    assert second.result is None
    assert second.passed
    assert deck.next_item(conn, TODAY) is None


def test_every_answer_is_logged(conn):
    c = add_card(conn, card(), today=TODAY).card
    InaccuracyDeck().record_answer(
        conn, c, attempts=2, used_show_answer=False, used_hint=True, today=TODAY
    )
    (row,) = repo.recent_reviews(conn)
    assert (row.quality, row.attempts, row.used_hint) == (3, 2, True)


def test_counts_report_due_total_and_the_next_date(conn):
    a = add_card(conn, card(2), today=TODAY).card
    add_card(conn, card(4), today=TODAY)
    make_due(conn, a.id)
    counts = InaccuracyDeck().counts(conn, TODAY)
    assert (counts.due, counts.total) == (1, 2)
    assert counts.next_due_on == TOMORROW
