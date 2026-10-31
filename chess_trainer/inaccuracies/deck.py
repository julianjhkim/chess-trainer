"""The inaccuracy deck: adding cards, serving them and recording answers.

Scheduling is the same modified SM-2 as the opening cards (:mod:`srs.sm2`,
graded by :mod:`srs.grading`), and a failed card comes back later in the same
session by the same rules (:mod:`srs.due`). What differs is where cards come
from: one is added whenever a review finishes with an inaccuracy, already
scheduled as if passed once -- due the next day, since it was just solved in
the review. Slipping into a position that already has a card brings that card
back to the next day instead of adding a second one.

Holds the per-session queue state; the database work is in
:mod:`db.inaccuracy_cards_repo`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from chess_trainer.db import inaccuracy_cards_repo as repo
from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard, InaccuracyReview
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.srs import due as due_rules
from chess_trainer.srs import grading, sm2
from chess_trainer.srs.due import CardSource, Requeued
from chess_trainer.srs.sm2 import SchedulingResult, SchedulingState

#: A new card is due this many days after the review that created it.
FIRST_INTERVAL_DAYS = 1


@dataclass(frozen=True, slots=True)
class AddResult:
    card: InaccuracyCard
    #: False when the position already had a card, which was brought forward.
    created: bool
    due_on: date


def add_card(conn: sqlite3.Connection, card: InaccuracyCard, *, today: date) -> AddResult:
    """Add a card from a review, or bring an existing one for the position back."""
    tomorrow = today + timedelta(days=FIRST_INTERVAL_DAYS)
    existing = repo.get_by_epd(conn, card.epd)
    if existing is not None and existing.id is not None:
        schedule = repo.get_schedule(conn, existing.id)
        if schedule is not None and schedule.due_on > tomorrow:
            schedule = repo.upsert_schedule(
                conn,
                ScheduleRow(
                    card_id=schedule.card_id,
                    n=schedule.n,
                    ef=schedule.ef,
                    interval_days=schedule.interval_days,
                    due_on=tomorrow,
                    last_reviewed_on=schedule.last_reviewed_on,
                    reps=schedule.reps,
                    lapses=schedule.lapses,
                ),
            )
        return AddResult(
            card=existing,
            created=False,
            due_on=schedule.due_on if schedule else tomorrow,
        )

    stored = repo.insert(conn, card)
    assert stored.id is not None
    repo.upsert_schedule(
        conn,
        ScheduleRow(
            card_id=stored.id,
            # As if passed once: the next pass goes to the 6-day step.
            n=1,
            ef=sm2.INITIAL_EF,
            interval_days=FIRST_INTERVAL_DAYS,
            due_on=tomorrow,
        ),
    )
    return AddResult(card=stored, created=True, due_on=tomorrow)


@dataclass(frozen=True, slots=True)
class DeckItem:
    card: InaccuracyCard
    source: CardSource
    schedule: ScheduleRow | None = None


@dataclass(frozen=True, slots=True)
class DeckAnswer:
    card: InaccuracyCard
    quality: int
    passed: bool
    requeued: bool
    attempts: int
    used_hint: bool
    #: None when the card was already rescheduled earlier in this session.
    result: SchedulingResult | None = None

    @property
    def description(self) -> str:
        return grading.describe(self.quality, self.attempts, self.used_hint)


@dataclass(frozen=True, slots=True)
class DeckCounts:
    due: int
    relearning: int
    total: int
    #: When the next card turns up, if nothing is due now.
    next_due_on: date | None = None


@dataclass
class InaccuracyDeck:
    """Per-session queue state. One instance lives on the app state."""

    gap: int = due_rules.REQUEUE_GAP
    served: int = 0
    _requeued: list[Requeued] = field(default_factory=list, repr=False)
    _scheduled: set[int] = field(default_factory=set, repr=False)

    def next_item(self, conn: sqlite3.Connection, today: date) -> DeckItem | None:
        """A failed card whose gap is up, else the oldest due card, else any failed one."""
        waiting = due_rules.eligible_requeue(self._requeued, served=self.served)
        if waiting is not None:
            item = self._relearn_item(conn, waiting)
            if item is not None:
                return item

        # A card failed this session was already rescheduled (often still due
        # today); it comes back through the requeue, not straight away.
        relearning = {r.card_id for r in self._requeued}
        for card, schedule in repo.due_cards(conn, today):
            if card.id not in relearning and card.id not in self._scheduled:
                return DeckItem(card=card, source=CardSource.DUE, schedule=schedule)

        forced = due_rules.forced_requeue(self._requeued)
        if forced is not None:
            return self._relearn_item(conn, forced)
        return None

    def _relearn_item(self, conn: sqlite3.Connection, waiting: Requeued) -> DeckItem | None:
        card = repo.get(conn, waiting.card_id)
        if card is None:  # pragma: no cover - deleted under us
            self._drop_requeued(waiting.card_id)
            return None
        return DeckItem(
            card=card,
            source=CardSource.RELEARN,
            schedule=repo.get_schedule(conn, waiting.card_id),
        )

    def mark_served(self) -> int:
        self.served += 1
        return self.served

    def record_answer(
        self,
        conn: sqlite3.Connection,
        card: InaccuracyCard,
        *,
        attempts: int,
        used_show_answer: bool,
        used_hint: bool,
        today: date,
    ) -> DeckAnswer:
        """Grade an answer; the first answer in a session decides the schedule."""
        assert card.id is not None
        quality = grading.quality_for(
            attempts=attempts, used_show_answer=used_show_answer, used_hint=used_hint
        )
        passed = grading.is_pass(quality)
        existing = repo.get_schedule(conn, card.id)

        result: SchedulingResult | None = None
        if card.id not in self._scheduled:
            state = (
                SchedulingState(
                    n=existing.n, ef=existing.ef, interval_days=existing.interval_days
                )
                if existing is not None
                else sm2.new_state()
            )
            result = sm2.review(state, quality, today=today)
            repo.upsert_schedule(
                conn,
                ScheduleRow(
                    card_id=card.id,
                    n=result.state.n,
                    ef=result.state.ef,
                    interval_days=result.state.interval_days,
                    due_on=result.due_on,
                    last_reviewed_on=today,
                    reps=(existing.reps if existing else 0) + 1,
                    lapses=(existing.lapses if existing else 0) + (0 if passed else 1),
                ),
            )
            self._scheduled.add(card.id)

        repo.record_review(
            conn,
            InaccuracyReview(
                card_id=card.id,
                reviewed_on=today,
                quality=quality,
                attempts=attempts,
                used_show_answer=used_show_answer,
                used_hint=used_hint,
                interval_days=result.interval_days if result else None,
                ef=result.state.ef if result else None,
            ),
        )

        if passed:
            self._drop_requeued(card.id)
        else:
            self._drop_requeued(card.id)
            self._requeued.append(
                Requeued(
                    card_id=card.id,
                    eligible_at=due_rules.schedule_requeue(served=self.served, gap=self.gap),
                )
            )
        return DeckAnswer(
            card=card,
            quality=quality,
            passed=passed,
            requeued=not passed,
            attempts=attempts,
            used_hint=used_hint,
            result=result,
        )

    def _drop_requeued(self, card_id: int) -> None:
        self._requeued = [r for r in self._requeued if r.card_id != card_id]

    def counts(self, conn: sqlite3.Connection, today: date) -> DeckCounts:
        relearning = {r.card_id for r in self._requeued}
        waiting_due = [
            card
            for card, _ in repo.due_cards(conn, today)
            if card.id not in relearning and card.id not in self._scheduled
        ]
        return DeckCounts(
            due=len(waiting_due),
            relearning=len(relearning),
            total=repo.count(conn),
            next_due_on=repo.next_due_on(conn, today),
        )

    def reset(self) -> None:
        self.served = 0
        self._requeued = []
        self._scheduled = set()
