from __future__ import annotations

import pytest

from chess_trainer.engine.classify import Classification, classify


@pytest.mark.parametrize(
    ("drop", "expected"),
    [
        (0.0, Classification.GOOD),
        (9.99, Classification.GOOD),
        (10.0, Classification.INACCURACY),
        (19.99, Classification.INACCURACY),
        (20.0, Classification.MISTAKE),
        (29.99, Classification.MISTAKE),
        (30.0, Classification.BLUNDER),
        (100.0, Classification.BLUNDER),
    ],
)
def test_thresholds(drop, expected):
    assert classify(drop) == expected


def test_boundaries_are_inclusive():
    assert classify(10.0) is Classification.INACCURACY
    assert classify(20.0) is Classification.MISTAKE
    assert classify(30.0) is Classification.BLUNDER


def test_is_inaccuracy_or_worse():
    assert not Classification.GOOD.is_inaccuracy_or_worse
    assert Classification.INACCURACY.is_inaccuracy_or_worse
    assert Classification.MISTAKE.is_inaccuracy_or_worse
    assert Classification.BLUNDER.is_inaccuracy_or_worse


def test_labels_are_capitalised():
    assert Classification.BLUNDER.label == "Blunder"


def test_values_are_stable_strings():
    assert [c.value for c in Classification] == [
        "good",
        "inaccuracy",
        "mistake",
        "blunder",
    ]
