"""The modified SM-2 scheduler.

Per card: ``n`` consecutive passes, an ease factor ``ef`` and an interval ``I``
in days.

Pass (``q >= 3``)::

    n == 0  ->  I = 1
    n == 1  ->  I = 6
    else        I = round(I * ef)
    n += 1

Fail (``q < 3``) departs from textbook SM-2, which drops straight back to one
day. Here the interval is halved instead, so a lapse on a card you have known
for months does not throw away all of that history::

    I = max(1, round(I * 0.5))
    n = 0

The ease factor moves the usual way, with a floor of 1.3::

    ef' = ef + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)

The interval is computed with the ease factor the card had *before* this
answer, and the factor is updated afterwards -- the order the rules are written
in, and what textbook SM-2 does.

Pure: no clock, no database. The caller supplies today's date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

#: Starting ease factor for a new card.
INITIAL_EF = 2.5

#: Ease factors never go below this.
MIN_EF = 1.3

#: The quality at or above which an answer counts as a pass.
PASS_QUALITY = 3

#: Interval after the first and second successful answers.
FIRST_INTERVAL = 1
SECOND_INTERVAL = 6

#: A lapse halves the interval rather than resetting it.
LAPSE_MULTIPLIER = 0.5
MIN_INTERVAL = 1


@dataclass(frozen=True, slots=True)
class SchedulingState:
    """A card's scheduling state."""

    n: int = 0
    ef: float = INITIAL_EF
    interval_days: int = 0

    @property
    def is_new(self) -> bool:
        return self.interval_days == 0 and self.n == 0


@dataclass(frozen=True, slots=True)
class SchedulingResult:
    """The state after an answer, and when the card is next due."""

    state: SchedulingState
    due_on: date
    passed: bool
    #: The interval before this answer, for reporting.
    previous_interval_days: int = 0

    @property
    def interval_days(self) -> int:
        return self.state.interval_days


def next_ef(ef: float, quality: int) -> float:
    """The updated ease factor, never below :data:`MIN_EF`."""
    delta = 5 - quality
    updated = ef + 0.1 - delta * (0.08 + delta * 0.02)
    return max(MIN_EF, updated)


def next_interval(state: SchedulingState, quality: int) -> int:
    """The interval in days after an answer of ``quality``."""
    if quality >= PASS_QUALITY:
        if state.n == 0:
            return FIRST_INTERVAL
        if state.n == 1:
            return SECOND_INTERVAL
        return max(MIN_INTERVAL, round(state.interval_days * state.ef))
    return max(MIN_INTERVAL, round(state.interval_days * LAPSE_MULTIPLIER))


def review(state: SchedulingState, quality: int, *, today: date) -> SchedulingResult:
    """Apply one answer to a card's state."""
    if not 0 <= quality <= 5:
        raise ValueError(f"quality must be between 0 and 5, got {quality}")

    passed = quality >= PASS_QUALITY
    interval = next_interval(state, quality)
    updated = SchedulingState(
        n=state.n + 1 if passed else 0,
        ef=next_ef(state.ef, quality),
        interval_days=interval,
    )
    return SchedulingResult(
        state=updated,
        due_on=today + timedelta(days=interval),
        passed=passed,
        previous_interval_days=state.interval_days,
    )


def new_state() -> SchedulingState:
    """The state of a card that has never been answered."""
    return SchedulingState()
