from __future__ import annotations

import pytest

from chess_trainer.chesscom.game_model import ChessComGame
from chess_trainer.chesscom.latest_game import (
    NoGamesFound,
    fetch_games_in_latest_archive,
    fetch_latest,
    most_recent,
    newer_than,
)

BASE = "https://api.chess.com/pub/player/test-player/games"


def game(game_id: str, end_time: int | None = 100, **overrides) -> ChessComGame:
    defaults = {
        "white_username": "test-player",
        "black_username": "rival",
        "rules": "chess",
    }
    defaults.update(overrides)
    return ChessComGame(id=game_id, pgn="1. e4 e5", end_time=end_time, **defaults)


class FakeClient:
    """Stands in for ChessComClient, serving canned archives."""

    def __init__(self, archives: dict[str, list[dict]], username="test-player"):
        self.username = username
        self._archives = archives
        self.fetched: list[str] = []

    def archive_urls(self) -> list[str]:
        return list(self._archives)

    def archive_games(self, archive_url: str) -> list[dict]:
        self.fetched.append(archive_url)
        return self._archives[archive_url]


def raw(game_id: str, end_time: int, white="test-player", rules="chess") -> dict:
    return {
        "uuid": game_id,
        "pgn": "1. e4 e5 1-0",
        "end_time": end_time,
        "rules": rules,
        "white": {"username": white},
        "black": {"username": "rival"},
    }


# -- most_recent ---------------------------------------------------------
def test_most_recent_of_nothing_is_none():
    assert most_recent([]) is None


def test_most_recent_picks_the_highest_end_time():
    games = [game("a", 100), game("c", 300), game("b", 200)]
    assert most_recent(games).id == "c"


def test_most_recent_does_not_trust_list_order():
    assert most_recent([game("old", 1), game("new", 999)]).id == "new"


def test_games_without_an_end_time_sort_oldest():
    assert most_recent([game("dated", 50), game("undated", None)]).id == "dated"


# -- newer_than ----------------------------------------------------------
def test_everything_is_new_when_nothing_was_seen():
    games = [game("a", 100), game("b", 200)]
    assert len(newer_than(games, None)) == 2


def test_the_reference_game_itself_is_not_new():
    games = [game("a", 100), game("b", 200)]
    assert [g.id for g in newer_than(games, "a", 100)] == ["b"]


def test_older_games_are_not_new():
    games = [game("old", 50), game("seen", 100), game("new", 150)]
    assert [g.id for g in newer_than(games, "seen", 100)] == ["new"]


def test_a_game_finishing_in_the_same_second_still_counts():
    """chess.com can report equal end times for back-to-back games."""
    games = [game("seen", 100), game("other", 100)]
    assert [g.id for g in newer_than(games, "seen", 100)] == ["other"]


def test_newer_than_with_no_end_time_reference():
    games = [game("seen", 100), game("new", 200)]
    assert [g.id for g in newer_than(games, "seen", None)] == ["new"]


# -- fetch_latest --------------------------------------------------------
def test_fetch_latest_returns_the_newest_game():
    client = FakeClient({f"{BASE}/2026/10": [raw("a", 100), raw("b", 200)]})
    assert fetch_latest(client).id == "b"


def test_fetch_latest_searches_the_newest_archive_first():
    client = FakeClient(
        {f"{BASE}/2025/01": [raw("old", 1)], f"{BASE}/2026/10": [raw("new", 200)]}
    )
    assert fetch_latest(client).id == "new"
    assert client.fetched[0].endswith("2026/10")


def test_an_empty_current_month_falls_through_to_the_previous_one():
    """Nothing played yet this month must not mean "no games"."""
    client = FakeClient(
        {f"{BASE}/2026/09": [raw("september", 100)], f"{BASE}/2026/10": []}
    )
    assert fetch_latest(client).id == "september"
    assert len(client.fetched) == 2


def test_variants_are_skipped():
    client = FakeClient(
        {f"{BASE}/2026/10": [raw("v", 300, rules="chess960"), raw("std", 100)]}
    )
    assert fetch_latest(client).id == "std"


def test_variants_can_be_allowed():
    client = FakeClient({f"{BASE}/2026/10": [raw("v", 300, rules="chess960")]})
    assert fetch_latest(client, standard_only=False).id == "v"


def test_other_peoples_games_are_skipped():
    client = FakeClient({f"{BASE}/2026/10": [raw("theirs", 300, white="someone")]})
    with pytest.raises(NoGamesFound):
        fetch_latest(client)


def test_no_archives_at_all_is_reported():
    with pytest.raises(NoGamesFound, match="no games"):
        fetch_latest(FakeClient({}))


def test_all_archives_empty_is_reported():
    client = FakeClient({f"{BASE}/2026/10": [], f"{BASE}/2026/09": []})
    with pytest.raises(NoGamesFound, match="No reviewable games"):
        fetch_latest(client)


def test_the_search_is_bounded():
    archives = {f"{BASE}/2026/{month:02d}": [] for month in range(1, 13)}
    client = FakeClient(archives)
    with pytest.raises(NoGamesFound):
        fetch_latest(client, max_archives=3)
    assert len(client.fetched) == 3


# -- fetch_games_in_latest_archive --------------------------------------
def test_latest_archive_games_returns_all_of_mine():
    client = FakeClient({f"{BASE}/2026/10": [raw("a", 100), raw("b", 200)]})
    assert {g.id for g in fetch_games_in_latest_archive(client)} == {"a", "b"}


def test_latest_archive_games_skips_empty_months():
    client = FakeClient({f"{BASE}/2026/10": [], f"{BASE}/2026/09": [raw("a", 1)]})
    assert [g.id for g in fetch_games_in_latest_archive(client)] == ["a"]


def test_latest_archive_games_of_an_empty_account_is_empty():
    assert fetch_games_in_latest_archive(FakeClient({})) == []
