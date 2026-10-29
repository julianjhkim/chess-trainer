from __future__ import annotations

from chess_trainer.db import state_repo


def test_get_missing_key_returns_none(conn):
    assert state_repo.get(conn, "nope") is None


def test_set_then_get_round_trips(conn):
    state_repo.set(conn, "colour", "white")
    assert state_repo.get(conn, "colour") == "white"


def test_set_overwrites_existing_value(conn):
    state_repo.set(conn, "k", "first")
    state_repo.set(conn, "k", "second")
    assert state_repo.get(conn, "k") == "second"
    assert conn.execute("SELECT COUNT(*) FROM app_state").fetchone()[0] == 1


def test_set_records_an_updated_timestamp(conn):
    state_repo.set(conn, "k", "v")
    stamp = conn.execute("SELECT updated_at FROM app_state WHERE key='k'").fetchone()[0]
    assert stamp.endswith("+00:00")


def test_delete_removes_the_key(conn):
    state_repo.set(conn, "k", "v")
    state_repo.delete(conn, "k")
    assert state_repo.get(conn, "k") is None


def test_delete_missing_key_is_harmless(conn):
    state_repo.delete(conn, "absent")


def test_last_seen_game_helpers(conn):
    assert state_repo.get_last_seen_game_id(conn) is None
    state_repo.set_last_seen_game_id(conn, "12345")
    assert state_repo.get_last_seen_game_id(conn) == "12345"
    assert state_repo.get(conn, state_repo.LAST_SEEN_GAME_KEY) == "12345"
