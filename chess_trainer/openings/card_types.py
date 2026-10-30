"""The card value types.

Pure definitions, shared by the rules, the builder and the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CardMode(str, Enum):
    """How a card's correct answer is decided."""

    #: 20+ master games: the most frequently played move.
    FREQUENCY = "frequency"
    #: 5-19 master games: too thin to trust, so Stockfish decides.
    ENGINE = "engine"


class CardStatus(str, Enum):
    ACTIVE = "active"
    #: Fewer than 5 master games: not a card, and the line stops here.
    DEAD_END = "dead_end"


@dataclass(frozen=True, slots=True)
class Answer:
    """The accepted move for a card."""

    uci: str
    mode: CardMode
    #: Other moves played exactly as often, when the engine broke a tie.
    tied_ucis: tuple[str, ...] = ()

    @property
    def was_tie_broken(self) -> bool:
        return len(self.tied_ucis) > 1


@dataclass(frozen=True, slots=True)
class Branch:
    """A move that leads to a child of this card."""

    uci: str
    games: int
    share: float


@dataclass(frozen=True, slots=True)
class CardPlan:
    """What the rules say about one position, before any engine call."""

    total_games: int
    status: CardStatus
    mode: CardMode | None = None
    #: The most-played move, or the tied set the engine must choose between.
    answer_candidates: tuple[str, ...] = ()
    branches: tuple[Branch, ...] = field(default_factory=tuple)
    #: True for the start position, which is not a card but does have branches.
    is_root: bool = False

    @property
    def is_card(self) -> bool:
        return self.status is CardStatus.ACTIVE and not self.is_root

    @property
    def needs_engine(self) -> bool:
        """Whether deciding the answer requires a search."""
        if self.mode is CardMode.ENGINE:
            return True
        return len(self.answer_candidates) > 1
