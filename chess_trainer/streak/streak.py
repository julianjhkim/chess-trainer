"""Streak arithmetic over a set of active days.

Pure: hand it the days on which something was completed, and it reports the
current and longest run. A day counts as active if at least one session step was
completed on it; this module does not care which.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class Streak:
    current: int
    longest: int
    #: True when today itself is active, i.e. the streak is already safe.
    active_today: bool
    total_days: int


def _runs(days: list[date]) -> list[list[date]]:
    """Split sorted, unique days into runs of consecutive calendar days."""
    runs: list[list[date]] = []
    for day in days:
        if runs and day - runs[-1][-1] == timedelta(days=1):
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs


def longest_run(days: Iterable[date]) -> int:
    ordered = sorted(set(days))
    return max((len(run) for run in _runs(ordered)), default=0)


def current_run(days: Iterable[date], *, today: date) -> int:
    """Length of the run ending today, or ending yesterday.

    A streak stays alive through today until the day is over: if yesterday was
    active but today has not been used yet, the streak still counts. It only
    breaks once a whole day has passed with nothing completed.
    """
    active = set(days)
    anchor: date | None = None
    if today in active:
        anchor = today
    elif (today - timedelta(days=1)) in active:
        anchor = today - timedelta(days=1)
    if anchor is None:
        return 0

    length = 0
    day = anchor
    while day in active:
        length += 1
        day -= timedelta(days=1)
    return length


def compute(days: Iterable[date], *, today: date) -> Streak:
    ordered = sorted(set(days))
    return Streak(
        current=current_run(ordered, today=today),
        longest=longest_run(ordered),
        active_today=today in set(ordered),
        total_days=len(ordered),
    )
