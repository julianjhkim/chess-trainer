"""Order in which new cards are introduced.

Breadth-first: every branch at one depth is drilled before anything deeper,
ordered by game count within each parent and by the order of the parents
themselves.

That falls out of one invariant rather than needing a sort at serve time: a
card's branches are created only when the card is first answered correctly, and
new cards are served in ``(depth, queue_seq)`` order, where ``queue_seq`` is a
counter assigned at creation. So parents are always created -- and therefore
answered -- before their children exist, and ordering by depth then sequence
reproduces exactly the intended order.

Due reviews never disturb it: expansion happens on a card's *first* correct
answer, and a card that is due has necessarily been answered before.
"""

from __future__ import annotations

from collections.abc import Iterable

from chess_trainer.openings.card_types import Branch


def sort_branches(branches: Iterable[Branch]) -> list[Branch]:
    """Branches most-played first, ties broken by UCI for determinism."""
    return sorted(branches, key=lambda b: (-b.games, b.uci))


def order_key(depth: int, queue_seq: int) -> tuple[int, int]:
    """The sort key used to serve new cards."""
    return (depth, queue_seq)


def next_sequence(current_max: int | None) -> int:
    """The sequence number for the next card created."""
    return (current_max or 0) + 1


def assign_sequences(
    branches: Iterable[Branch], *, start: int
) -> list[tuple[Branch, int]]:
    """Pair each branch with its sequence number, in game-count order."""
    return [
        (branch, start + offset)
        for offset, branch in enumerate(sort_branches(branches))
    ]
