"""Which card comes next.

Due reviews come first, oldest due date first; then new cards, one at a time.
There is no daily limit -- the session runs until you stop.

A card that was failed earlier in the same session has to come back before the
session ends, but not immediately, so it is reinserted after a gap of a few
other cards. If nothing else is left, the gap is ignored rather than leaving
the card unanswered.

Pure: ordering and eligibility only; the database work is in
:mod:`chess_trainer.srs.scheduler`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.schedule_repo import ScheduleRow

#: How many other cards to show before a failed card comes round again.
REQUEUE_GAP = 3


class CardSource(str, Enum):
    """Why this card is being shown."""

    DUE = "due"
    NEW = "new"
    #: Failed earlier in this session and coming round again.
    RELEARN = "relearn"


@dataclass(frozen=True, slots=True)
class QueueItem:
    card: CardRow
    source: CardSource
    schedule: ScheduleRow | None = None

    @property
    def is_new(self) -> bool:
        return self.source is CardSource.NEW


@dataclass(frozen=True, slots=True)
class Requeued:
    """A card waiting to be shown again in this session."""

    card_id: int
    #: The value of the session's served counter at which it becomes eligible.
    eligible_at: int


def is_due(schedule: ScheduleRow, today: date) -> bool:
    return schedule.due_on <= today


def order_due(
    entries: list[tuple[CardRow, ScheduleRow]],
) -> list[tuple[CardRow, ScheduleRow]]:
    """Oldest due date first, then breadth-first order for a stable sequence."""
    return sorted(
        entries, key=lambda pair: (pair[1].due_on, pair[0].depth, pair[0].queue_seq)
    )


def eligible_requeue(
    requeued: list[Requeued], *, served: int
) -> Requeued | None:
    """The first requeued card whose gap has elapsed."""
    for item in requeued:
        if item.eligible_at <= served:
            return item
    return None


def forced_requeue(requeued: list[Requeued]) -> Requeued | None:
    """The first requeued card, gap or not.

    Used when there is nothing else to show, so a failed card is never left
    unanswered just because the session ran out of other material.
    """
    return requeued[0] if requeued else None


def schedule_requeue(*, served: int, gap: int = REQUEUE_GAP) -> int:
    """When a card failed now should become eligible again."""
    return served + gap
