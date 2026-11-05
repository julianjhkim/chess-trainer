"""Which sides of which openings I study.

Pure. The rule everywhere: on my own moves I study only the main move; on the
opponent's, every reply the tree rules allow. So a card always asks my move
and branches only through its answer, and the opponent's replies after it are
the next cards (``card_builder``).

As Black I meet every first move, so every first move is a card for my Black
side. As White I play only 1.e4, 1.d4, 1.Nf3 and 1.c4: after those, each Black
reply is a card asking my White move. Any other first move is Black-only.
"""

from __future__ import annotations

from collections.abc import Sequence

#: My first moves as White: 1.e4, 1.d4, 1.Nf3 and 1.c4.
WHITE_FIRST_MOVES = frozenset({"e2e4", "d2d4", "g1f3", "c2c4"})


def black_only(ucis: Sequence[str]) -> bool:
    """Whether a line starts with a first move I only meet as Black."""
    return bool(ucis) and ucis[0] not in WHITE_FIRST_MOVES
