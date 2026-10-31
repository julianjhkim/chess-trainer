"""The session's steps and their canonical order.

Pure definitions only: no state, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Step(str, Enum):
    """The four steps of a daily session, in the order they run.

    Inaccuracy cards come first, to warm up on your own past slips before
    playing; the game you then play is reviewed, and its first slip becomes a
    new inaccuracy card.
    """

    INACCURACY_CARDS = "inaccuracy_cards"
    PLAY = "play"
    REVIEW_NEW_GAME = "review_new_game"
    CARDS = "cards"

    @property
    def position(self) -> int:
        """1-based position in the canonical order."""
        return ORDER.index(self) + 1

    @property
    def title(self) -> str:
        return TITLES[self]


#: Canonical running order.
ORDER: tuple[Step, ...] = (
    Step.INACCURACY_CARDS,
    Step.PLAY,
    Step.REVIEW_NEW_GAME,
    Step.CARDS,
)

TITLES: dict[Step, str] = {
    Step.INACCURACY_CARDS: "Inaccuracy cards",
    Step.PLAY: "Play a game",
    Step.REVIEW_NEW_GAME: "Review that game",
    Step.CARDS: "Opening cards",
}

#: Every step is selected by default on the start screen.
DEFAULT_ENABLED: frozenset[Step] = frozenset(ORDER)


@dataclass(frozen=True, slots=True)
class StepInfo:
    step: Step
    position: int
    title: str
    enabled: bool
    completed: bool
    current: bool


def parse(value: str) -> Step:
    """Parse a step name, with a helpful error for the API layer."""
    try:
        return Step(value)
    except ValueError as exc:
        valid = ", ".join(s.value for s in ORDER)
        raise ValueError(f"Unknown step {value!r}; expected one of: {valid}") from exc


def sort_steps(steps: set[Step] | frozenset[Step]) -> list[Step]:
    """The given steps in canonical order."""
    return [s for s in ORDER if s in steps]


def next_after(step: Step, enabled: set[Step] | frozenset[Step]) -> Step | None:
    """The next enabled step after ``step``, or ``None`` at the end."""
    for candidate in ORDER[ORDER.index(step) + 1 :]:
        if candidate in enabled:
            return candidate
    return None


def first_enabled(enabled: set[Step] | frozenset[Step]) -> Step | None:
    for candidate in ORDER:
        if candidate in enabled:
            return candidate
    return None
