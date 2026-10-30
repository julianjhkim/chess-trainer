"""Serving cards and recording answers.

Holds the per-session queue state -- which cards were failed and when they
become eligible again, and which have already been rescheduled -- and does the
database work around :mod:`chess_trainer.srs.sm2`.

The "do not reschedule twice" rule lives here: the *first* answer to a card in a
session decides its schedule. Answering it again later in the same session (the
retry of a card that was failed) only clears it from the requeue.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from chess_trainer.db import cards_repo, review_log_repo, schedule_repo
from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.review_log_repo import CardReview
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.srs import due as due_rules
from chess_trainer.srs import grading, sm2
from chess_trainer.srs.due import CardSource, QueueItem, Requeued
from chess_trainer.srs.sm2 import SchedulingResult, SchedulingState


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    """What happened when a card was answered."""

    card: CardRow
    quality: int
    passed: bool
    #: False when the card had already been scheduled earlier in this session.
    rescheduled: bool
    was_new: bool
    #: True when the card goes back into this session's queue.
    requeued: bool
    result: SchedulingResult | None = None

    @property
    def interval_days(self) -> int | None:
        return self.result.interval_days if self.result else None

    @property
    def due_on(self) -> date | None:
        return self.result.due_on if self.result else None

    @property
    def ef(self) -> float | None:
        return self.result.state.ef if self.result else None


@dataclass(frozen=True, slots=True)
class QueueCounts:
    due: int
    new: int
    relearning: int

    @property
    def total_waiting(self) -> int:
        return self.due + self.new + self.relearning


@dataclass
class CardQueue:
    """Per-session queue state. One instance lives on the app state."""

    gap: int = due_rules.REQUEUE_GAP
    served: int = 0
    _requeued: list[Requeued] = field(default_factory=list, repr=False)
    _scheduled: set[int] = field(default_factory=set, repr=False)

    # -- serving ---------------------------------------------------------
    def next_item(self, conn: sqlite3.Connection, today: date) -> QueueItem | None:
        """The next card to show, or ``None`` when nothing is waiting."""
        waiting = due_rules.eligible_requeue(self._requeued, served=self.served)
        if waiting is not None:
            item = self._relearn_item(conn, waiting)
            if item is not None:
                return item

        found = schedule_repo.next_due(conn, today)
        if found is not None:
            card, schedule = found
            return QueueItem(card=card, source=CardSource.DUE, schedule=schedule)

        new_card = cards_repo.next_new_card(conn)
        if new_card is not None:
            return QueueItem(card=new_card, source=CardSource.NEW)

        # Nothing else left: show a failed card even though its gap has not
        # elapsed, rather than ending the session with it unanswered.
        forced = due_rules.forced_requeue(self._requeued)
        if forced is not None:
            return self._relearn_item(conn, forced)
        return None

    def _relearn_item(
        self, conn: sqlite3.Connection, waiting: Requeued
    ) -> QueueItem | None:
        card = cards_repo.get(conn, waiting.card_id)
        if card is None:  # pragma: no cover - the card was deleted under us
            self._drop_requeued(waiting.card_id)
            return None
        return QueueItem(
            card=card,
            source=CardSource.RELEARN,
            schedule=schedule_repo.get(conn, waiting.card_id),
        )

    def mark_served(self) -> int:
        """Count a card as shown; drives the requeue gap."""
        self.served += 1
        return self.served

    # -- answering -------------------------------------------------------
    def record_answer(
        self,
        conn: sqlite3.Connection,
        card: CardRow,
        *,
        attempts: int,
        used_show_answer: bool,
        today: date,
    ) -> AnswerOutcome:
        """Grade an answer, scheduling the card the first time it is answered."""
        assert card.id is not None
        quality = grading.quality_for(
            attempts=attempts, used_show_answer=used_show_answer
        )
        passed = grading.is_pass(quality)
        already_scheduled = card.id in self._scheduled
        existing = schedule_repo.get(conn, card.id)
        was_new = existing is None

        result: SchedulingResult | None = None
        if not already_scheduled:
            state = (
                SchedulingState(
                    n=existing.n, ef=existing.ef, interval_days=existing.interval_days
                )
                if existing is not None
                else sm2.new_state()
            )
            result = sm2.review(state, quality, today=today)
            schedule_repo.upsert(
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

        review_log_repo.record(
            conn,
            CardReview(
                card_id=card.id,
                reviewed_on=today,
                quality=quality,
                attempts=attempts,
                used_show_answer=used_show_answer,
                was_new=was_new and not already_scheduled,
                interval_days=result.interval_days if result else None,
                ef=result.state.ef if result else None,
            ),
        )

        if passed:
            self._drop_requeued(card.id)
            requeued = False
        else:
            self._requeue(card.id)
            requeued = True

        return AnswerOutcome(
            card=card,
            quality=quality,
            passed=passed,
            rescheduled=not already_scheduled,
            was_new=was_new and not already_scheduled,
            requeued=requeued,
            result=result,
        )

    # -- requeue bookkeeping ---------------------------------------------
    def _requeue(self, card_id: int) -> None:
        self._drop_requeued(card_id)
        self._requeued.append(
            Requeued(
                card_id=card_id,
                eligible_at=due_rules.schedule_requeue(served=self.served, gap=self.gap),
            )
        )

    def _drop_requeued(self, card_id: int) -> None:
        self._requeued = [r for r in self._requeued if r.card_id != card_id]

    @property
    def relearning_ids(self) -> list[int]:
        return [r.card_id for r in self._requeued]

    def reset(self) -> None:
        """Start a fresh session: forget the requeue and the scheduled set."""
        self.served = 0
        self._requeued = []
        self._scheduled = set()

    # -- reporting -------------------------------------------------------
    def counts(self, conn: sqlite3.Connection, today: date) -> QueueCounts:
        return QueueCounts(
            due=schedule_repo.count_due(conn, today),
            new=cards_repo.count_new(conn),
            relearning=len(self._requeued),
        )
