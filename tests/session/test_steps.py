from __future__ import annotations

import pytest

from chess_trainer.session import steps as steps_module
from chess_trainer.session.steps import (
    DEFAULT_ENABLED,
    ORDER,
    Step,
    first_enabled,
    next_after,
    parse,
    sort_steps,
)


def test_there_are_four_steps_in_spec_order():
    assert ORDER == (
        Step.REVIEW_LAST_GAME,
        Step.PLAY,
        Step.REVIEW_NEW_GAME,
        Step.CARDS,
    )


def test_positions_are_one_based():
    assert [s.position for s in ORDER] == [1, 2, 3, 4]


def test_every_step_has_a_title():
    assert all(s.title for s in ORDER)
    assert Step.PLAY.title == "Play a game"


def test_all_steps_are_enabled_by_default():
    assert DEFAULT_ENABLED == frozenset(ORDER)


def test_steps_serialise_as_their_value():
    assert Step.CARDS.value == "cards"
    assert str(Step.CARDS) == "Step.CARDS"


def test_parse_accepts_known_names():
    assert parse("cards") is Step.CARDS


def test_parse_rejects_unknown_names_helpfully():
    with pytest.raises(ValueError, match="Unknown step"):
        parse("nonsense")
    with pytest.raises(ValueError, match="review_last_game"):
        parse("nonsense")


def test_sort_steps_uses_canonical_order():
    assert sort_steps({Step.CARDS, Step.REVIEW_LAST_GAME}) == [
        Step.REVIEW_LAST_GAME,
        Step.CARDS,
    ]


def test_next_after_skips_disabled_steps():
    enabled = {Step.REVIEW_LAST_GAME, Step.CARDS}
    assert next_after(Step.REVIEW_LAST_GAME, enabled) is Step.CARDS


def test_next_after_the_last_step_is_none():
    assert next_after(Step.CARDS, set(ORDER)) is None


def test_next_after_with_nothing_left_is_none():
    assert next_after(Step.PLAY, {Step.REVIEW_LAST_GAME}) is None


def test_first_enabled_follows_canonical_order():
    assert first_enabled({Step.CARDS, Step.PLAY}) is Step.PLAY


def test_first_enabled_of_nothing_is_none():
    assert first_enabled(set()) is None


def test_titles_cover_every_step():
    assert set(steps_module.TITLES) == set(ORDER)
