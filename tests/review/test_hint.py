from __future__ import annotations

import pytest

from chess_trainer.review.hint import hint_for

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_a_hint_names_the_piece_on_the_square():
    hint = hint_for(START, "g1")
    assert hint.square == "g1"
    assert hint.piece == "knight"


def test_a_hint_reads_as_a_sentence():
    assert hint_for(START, "e2").text == "Move your pawn on e2."


def test_an_empty_square_is_an_error():
    with pytest.raises(ValueError):
        hint_for(START, "e4")
