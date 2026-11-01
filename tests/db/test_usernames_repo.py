from __future__ import annotations

from chess_trainer.db import usernames_repo


def test_the_first_read_seeds_from_the_env_name(conn):
    assert usernames_repo.get(conn, seed="test-player") == ["test-player"]
    # Seeded once: clearing the list is respected afterwards.
    usernames_repo.put(conn, [])
    assert usernames_repo.get(conn, seed="test-player") == []


def test_no_seed_means_an_empty_list(conn):
    assert usernames_repo.get(conn) == []


def test_put_stores_a_cleaned_list(conn):
    stored = usernames_repo.put(conn, [" first ", "second", "FIRST"])
    assert stored == ["first", "second"]
    assert usernames_repo.get(conn, seed="ignored") == ["first", "second"]
