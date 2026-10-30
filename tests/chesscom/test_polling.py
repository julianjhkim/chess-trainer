"""Polling tests with an injected clock and sleep: no real waiting."""

from __future__ import annotations

import pytest

from chess_trainer.chesscom.client import ChessComUnavailable, PlayerNotFound
from chess_trainer.chesscom.game_model import ChessComGame
from chess_trainer.chesscom.polling import (
    TOTAL_BUDGET_SECONDS,
    WINDOW_SECONDS,
    poll_for_new_game,
)


def game(game_id: str, end_time: int = 200) -> ChessComGame:
    return ChessComGame(id=game_id, pgn="1. e4", end_time=end_time)


class FakeClock:
    """A clock that only advances when `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_a_new_game_is_returned_immediately():
    clock = FakeClock()
    result = poll_for_new_game(
        lambda: [game("new", 300)],
        last_seen_id="old",
        last_seen_end_time=100,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.found
    assert result.game.id == "new"
    assert result.attempts == 1
    assert clock.slept == []


def test_nothing_new_exhausts_the_budget():
    clock = FakeClock()
    result = poll_for_new_game(
        lambda: [game("old", 100)],
        last_seen_id="old",
        last_seen_end_time=100,
        budget_seconds=12.0,
        interval_seconds=3.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert not result.found
    assert result.attempts == 4  # at 0s, 3s, 6s, 9s
    assert clock.slept == [3.0, 3.0, 3.0]


def test_a_game_appearing_part_way_through_is_found():
    """The archive lags, then catches up."""
    clock = FakeClock()
    responses = [[], [], [game("new", 300)]]

    def fetch():
        return responses.pop(0)

    result = poll_for_new_game(
        fetch,
        last_seen_id="old",
        last_seen_end_time=100,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.found
    assert result.attempts == 3
    assert result.waited == pytest.approx(6.0)


def test_the_newest_of_several_new_games_wins():
    clock = FakeClock()
    result = poll_for_new_game(
        lambda: [game("a", 300), game("b", 500)],
        last_seen_id="old",
        last_seen_end_time=100,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.game.id == "b"


def test_with_no_last_seen_game_any_game_counts():
    clock = FakeClock()
    result = poll_for_new_game(
        lambda: [game("whatever", 1)],
        last_seen_id=None,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.found


def test_transient_errors_are_retried_within_the_budget():
    clock = FakeClock()
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ChessComUnavailable("flaky")
        return [game("new", 300)]

    result = poll_for_new_game(
        fetch,
        last_seen_id="old",
        last_seen_end_time=100,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.found
    assert result.attempts == 3
    assert result.error is None


def test_a_persistent_error_is_reported_without_raising():
    clock = FakeClock()

    def fetch():
        raise ChessComUnavailable("still down")

    result = poll_for_new_game(
        fetch,
        last_seen_id="old",
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert not result.found
    assert result.error == "still down"


def test_an_error_that_later_clears_is_not_reported():
    clock = FakeClock()
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ChessComUnavailable("blip")
        return [game("old", 100)]

    result = poll_for_new_game(
        fetch,
        last_seen_id="old",
        last_seen_end_time=100,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert not result.found
    assert result.error is None


def test_a_bad_username_is_not_transient():
    clock = FakeClock()

    def fetch():
        raise PlayerNotFound("no such player")

    with pytest.raises(PlayerNotFound):
        poll_for_new_game(
            fetch,
            last_seen_id="old",
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )


def test_a_tiny_budget_still_makes_one_attempt():
    clock = FakeClock()
    result = poll_for_new_game(
        lambda: [],
        last_seen_id="old",
        budget_seconds=0.1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.attempts == 1
    assert clock.slept == []


def test_the_spec_budget_is_two_minutes():
    assert TOTAL_BUDGET_SECONDS == 120.0
    assert WINDOW_SECONDS < TOTAL_BUDGET_SECONDS
