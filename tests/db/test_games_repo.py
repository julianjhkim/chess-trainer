from __future__ import annotations

from chess_trainer.db import games_repo
from chess_trainer.db.games_repo import SOURCE_CHESSCOM, SOURCE_PASTE, StoredGame

PGN = '[White "me"]\n[Black "you"]\n\n1. e4 e5 *\n'


def game(game_id="g1", **overrides) -> StoredGame:
    base = dict(
        id=game_id,
        pgn=PGN,
        my_color="white",
        url="https://www.chess.com/game/live/1",
        white_username="test-player",
        black_username="rival",
        white_result="win",
        black_result="resigned",
        time_class="rapid",
        rules="chess",
        end_time=1000,
        source=SOURCE_CHESSCOM,
    )
    base.update(overrides)
    return StoredGame(**base)


def test_empty_repository(conn):
    assert games_repo.latest(conn) is None
    assert games_repo.count(conn) == 0
    assert games_repo.recent(conn) == []
    assert not games_repo.exists(conn, "nope")


def test_upsert_then_get(conn):
    games_repo.upsert(conn, game())
    stored = games_repo.get(conn, "g1")
    assert stored.pgn == PGN
    assert stored.my_color == "white"
    assert stored.time_class == "rapid"
    assert stored.source == SOURCE_CHESSCOM


def test_fetched_at_is_set_automatically(conn):
    stored = games_repo.upsert(conn, game())
    assert stored.fetched_at and stored.fetched_at.endswith("+00:00")


def test_exists(conn):
    games_repo.upsert(conn, game())
    assert games_repo.exists(conn, "g1")
    assert not games_repo.exists(conn, "g2")


def test_upsert_is_idempotent(conn):
    games_repo.upsert(conn, game())
    games_repo.upsert(conn, game())
    assert games_repo.count(conn) == 1


def test_upsert_updates_an_existing_row(conn):
    games_repo.upsert(conn, game())
    games_repo.upsert(conn, game(my_color="black", time_class="blitz"))
    stored = games_repo.get(conn, "g1")
    assert stored.my_color == "black"
    assert stored.time_class == "blitz"


def test_fetched_at_survives_an_update(conn):
    first = games_repo.upsert(conn, game())
    second = games_repo.upsert(conn, game(time_class="blitz"))
    assert second.fetched_at == first.fetched_at


def test_latest_uses_end_time(conn):
    games_repo.upsert(conn, game("old", end_time=100))
    games_repo.upsert(conn, game("new", end_time=500))
    assert games_repo.latest(conn).id == "new"


def test_latest_falls_back_to_fetched_at_for_undated_games(conn):
    games_repo.upsert(conn, game("undated", end_time=None, source=SOURCE_PASTE))
    assert games_repo.latest(conn).id == "undated"


def test_a_dated_game_beats_an_undated_one(conn):
    games_repo.upsert(conn, game("undated", end_time=None))
    games_repo.upsert(conn, game("dated", end_time=50))
    assert games_repo.latest(conn).id == "dated"


def test_recent_is_newest_first(conn):
    for n, end_time in (("a", 100), ("b", 300), ("c", 200)):
        games_repo.upsert(conn, game(n, end_time=end_time))
    assert [g.id for g in games_repo.recent(conn)] == ["b", "c", "a"]


def test_recent_respects_the_limit(conn):
    for n in range(5):
        games_repo.upsert(conn, game(f"g{n}", end_time=n))
    assert len(games_repo.recent(conn, limit=2)) == 2


def test_opponent_is_the_other_player(conn):
    white = games_repo.upsert(conn, game("w", my_color="white"))
    black = games_repo.upsert(conn, game("b", my_color="black"))
    assert white.opponent == "rival"
    assert black.opponent == "test-player"


def test_my_result_follows_my_colour(conn):
    white = games_repo.upsert(conn, game("w", my_color="white"))
    black = games_repo.upsert(conn, game("b", my_color="black"))
    assert white.my_result == "win"
    assert black.my_result == "resigned"


def test_my_color_is_white_flag():
    assert game(my_color="white").my_color_is_white
    assert not game(my_color="black").my_color_is_white


def test_an_invalid_colour_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        games_repo.upsert(conn, game(my_color="green"))


def test_an_invalid_source_is_rejected(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        games_repo.upsert(conn, game(source="telepathy"))


def test_a_pasted_game_round_trips(conn):
    games_repo.upsert(conn, game("p", source=SOURCE_PASTE, url=None, end_time=None))
    stored = games_repo.get(conn, "p")
    assert stored.source == SOURCE_PASTE
    assert stored.url is None
