from __future__ import annotations

import pytest

from chess_trainer.review.outcome import from_chesscom, from_pgn_result, my_outcome


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("win", "win"),
        ("agreed", "draw"),
        ("repetition", "draw"),
        ("stalemate", "draw"),
        ("insufficient", "draw"),
        ("50move", "draw"),
        ("timevsinsufficient", "draw"),
        ("checkmated", "loss"),
        ("resigned", "loss"),
        ("timeout", "loss"),
        ("abandoned", "loss"),
        (None, None),
        ("", None),
    ],
)
def test_chesscom_codes(code, expected):
    assert from_chesscom(code) == expected


@pytest.mark.parametrize(
    ("result", "colour", "expected"),
    [
        ("1-0", "white", "win"),
        ("1-0", "black", "loss"),
        ("0-1", "black", "win"),
        ("0-1", "white", "loss"),
        ("1/2-1/2", "white", "draw"),
        ("1/2-1/2", "black", "draw"),
        ("*", "white", None),
        (None, "white", None),
    ],
)
def test_pgn_results(result, colour, expected):
    assert from_pgn_result(result, colour) == expected


def test_chesscom_wins_over_the_pgn_header():
    assert my_outcome("win", "0-1", "white") == "win"


def test_the_pgn_header_is_the_fallback():
    assert my_outcome(None, "1/2-1/2", "black") == "draw"
