"""Typed view of a masters-database response.

Pure: these types are built from decoded JSON and know nothing about HTTP, so
the tree rules and the stats table can be tested without a network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Opening:
    """An opening name as the explorer reports it."""

    eco: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.eco} {self.name}"

    @classmethod
    def of(cls, payload: Any) -> "Opening | None":
        if not isinstance(payload, dict):
            return None
        eco = payload.get("eco")
        name = payload.get("name")
        if not isinstance(eco, str) or not isinstance(name, str):
            return None
        return cls(eco=eco, name=name)


@dataclass(frozen=True, slots=True)
class MoveStat:
    """One candidate move, with its master-game record."""

    uci: str
    san: str
    white: int
    draws: int
    black: int
    average_rating: int | None = None
    #: The opening of the position *after* this move.
    opening: Opening | None = None

    @property
    def games(self) -> int:
        return self.white + self.draws + self.black

    def share_of(self, total_games: int) -> float:
        """This move's percentage of a position's games (0 when empty)."""
        if total_games <= 0:
            return 0.0
        return 100.0 * self.games / total_games

    @classmethod
    def of(cls, payload: dict[str, Any]) -> "MoveStat":
        rating = payload.get("averageRating")
        return cls(
            uci=str(payload["uci"]),
            san=str(payload.get("san") or payload["uci"]),
            white=int(payload.get("white") or 0),
            draws=int(payload.get("draws") or 0),
            black=int(payload.get("black") or 0),
            average_rating=int(rating) if isinstance(rating, (int, float)) else None,
            opening=Opening.of(payload.get("opening")),
        )


@dataclass(frozen=True, slots=True)
class PositionStats:
    """The explorer's record for one position."""

    white: int
    draws: int
    black: int
    moves: list[MoveStat] = field(default_factory=list)
    #: The opening of this position itself (``None`` at the start position).
    opening: Opening | None = None

    @property
    def total_games(self) -> int:
        """Master games that reached this position."""
        return self.white + self.draws + self.black

    @property
    def is_empty(self) -> bool:
        return self.total_games == 0

    def by_games(self) -> list[MoveStat]:
        """Moves ordered by game count, most played first.

        Ties are broken by UCI so the order is deterministic; which of several
        equally played moves is *correct* is decided by the engine elsewhere.
        """
        return sorted(self.moves, key=lambda m: (-m.games, m.uci))

    def move(self, uci: str) -> MoveStat | None:
        return next((m for m in self.moves if m.uci == uci), None)

    @classmethod
    def of(cls, payload: dict[str, Any]) -> "PositionStats":
        raw_moves = payload.get("moves")
        moves = (
            [MoveStat.of(m) for m in raw_moves if isinstance(m, dict) and m.get("uci")]
            if isinstance(raw_moves, list)
            else []
        )
        return cls(
            white=int(payload.get("white") or 0),
            draws=int(payload.get("draws") or 0),
            black=int(payload.get("black") or 0),
            moves=moves,
            opening=Opening.of(payload.get("opening")),
        )
