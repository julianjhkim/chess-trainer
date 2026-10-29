"""The evaluation value type.

An :class:`Eval` is always stored from **White's** perspective, which gives the
database and the eval bar a single unambiguous convention. Use :meth:`Eval.pov`
to read it from the side that is to move.

This module deliberately knows nothing about UCI or subprocesses, so the maths
built on top of it is testable without an engine.
"""

from __future__ import annotations

from dataclasses import dataclass

WHITE = True
BLACK = False


@dataclass(frozen=True, slots=True)
class Eval:
    """A Stockfish evaluation, from White's perspective.

    Exactly one of ``cp`` and ``mate`` is set.

    ``cp`` is centipawns: positive favours White.
    ``mate`` is a distance in moves: ``+3`` means White mates in 3, ``-2`` means
    Black mates in 2. ``mate=0`` is not meaningful and is rejected.
    """

    cp: int | None = None
    mate: int | None = None

    def __post_init__(self) -> None:
        if (self.cp is None) == (self.mate is None):
            raise ValueError("Eval needs exactly one of cp or mate")
        if self.mate == 0:
            raise ValueError("mate=0 is not a valid mate distance")

    # -- constructors ----------------------------------------------------
    @classmethod
    def centipawns(cls, cp: int) -> "Eval":
        return cls(cp=int(cp))

    @classmethod
    def mate_in(cls, moves: int) -> "Eval":
        """``moves > 0``: White mates. ``moves < 0``: Black mates."""
        return cls(mate=int(moves))

    @classmethod
    def from_pov(cls, *, cp: int | None, mate: int | None, white_to_move: bool) -> "Eval":
        """Build from a score reported relative to the side to move."""
        if white_to_move:
            return cls(cp=cp, mate=mate)
        return cls(
            cp=-cp if cp is not None else None,
            mate=-mate if mate is not None else None,
        )

    # -- reading ---------------------------------------------------------
    @property
    def is_mate(self) -> bool:
        return self.mate is not None

    def pov(self, white: bool) -> "Eval":
        """This evaluation as the given side sees it (positive = good for them)."""
        if white:
            return self
        return Eval(
            cp=-self.cp if self.cp is not None else None,
            mate=-self.mate if self.mate is not None else None,
        )

    def flip(self) -> "Eval":
        return self.pov(BLACK)

    @property
    def mate_favours_white(self) -> bool | None:
        if self.mate is None:
            return None
        return self.mate > 0
