"""Which first moves I play as White, and what that means for the tree.

Pure. A line that starts with one of my White first moves is studied from both
sides. Any other first move I only ever meet as Black, so its tree asks only
Black's moves: one card per Black-to-move position, answered with the main
move (most played, or the engine's when the games are few), and no card where
White is to move -- White's replies branch straight through to the next
Black-to-move position, by the usual rules.
"""

from __future__ import annotations

from collections.abc import Sequence

#: My first moves as White: 1.e4, 1.d4, 1.Nf3 and 1.c4.
WHITE_FIRST_MOVES = frozenset({"e2e4", "d2d4", "g1f3", "c2c4"})


def black_only(ucis: Sequence[str]) -> bool:
    """Whether a line starts with a first move I only meet as Black."""
    return bool(ucis) and ucis[0] not in WHITE_FIRST_MOVES
