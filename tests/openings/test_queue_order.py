from __future__ import annotations

from chess_trainer.openings.card_types import Branch
from chess_trainer.openings.queue_order import (
    assign_sequences,
    next_sequence,
    order_key,
    sort_branches,
)


def branch(uci: str, games: int) -> Branch:
    return Branch(uci=uci, games=games, share=0.0)


def test_branches_sort_by_game_count():
    branches = [branch("a", 10), branch("b", 100), branch("c", 50)]
    assert [b.uci for b in sort_branches(branches)] == ["b", "c", "a"]


def test_ties_sort_by_uci_for_determinism():
    branches = [branch("e2e4", 10), branch("d2d4", 10)]
    assert [b.uci for b in sort_branches(branches)] == ["d2d4", "e2e4"]


def test_sorting_does_not_mutate_the_input():
    branches = [branch("a", 1), branch("b", 2)]
    sort_branches(branches)
    assert [b.uci for b in branches] == ["a", "b"]


def test_order_key_is_depth_then_sequence():
    assert order_key(2, 17) == (2, 17)
    assert order_key(1, 99) < order_key(2, 1)


def test_depth_dominates_the_sequence():
    """All of one depth is drilled before anything deeper."""
    assert sorted([(2, 1), (1, 500), (1, 2)]) == [(1, 2), (1, 500), (2, 1)]


def test_next_sequence_increments():
    assert next_sequence(0) == 1
    assert next_sequence(41) == 42


def test_next_sequence_of_nothing_starts_at_one():
    assert next_sequence(None) == 1


def test_assign_sequences_numbers_in_game_order():
    branches = [branch("a", 10), branch("b", 100), branch("c", 50)]
    assigned = assign_sequences(branches, start=5)
    assert [(b.uci, n) for b, n in assigned] == [("b", 5), ("c", 6), ("a", 7)]


def test_assign_sequences_of_nothing_is_empty():
    assert assign_sequences([], start=1) == []
