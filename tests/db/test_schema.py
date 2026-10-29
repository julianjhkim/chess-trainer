from __future__ import annotations

from chess_trainer.db import schema
from chess_trainer.db.connection import open_memory_db


def test_fresh_database_starts_at_version_zero():
    conn = open_memory_db()
    assert schema.current_version(conn) == 0
    conn.close()


def test_migrate_applies_everything_and_sets_version():
    conn = open_memory_db()
    applied = schema.migrate(conn)
    assert [m.version for m in applied] == [m.version for m in schema.MIGRATIONS]
    assert schema.current_version(conn) == schema.latest_version()
    conn.close()


def test_migrate_is_idempotent():
    conn = open_memory_db()
    schema.migrate(conn)
    assert schema.migrate(conn) == []
    conn.close()


def test_expected_tables_exist_after_migration(conn):
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"app_state", "day_activity", "analysis_cache"} <= names


def test_migration_versions_are_unique_and_ordered():
    versions = [m.version for m in schema.MIGRATIONS]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions[0] == 1


def test_pending_reflects_current_version():
    conn = open_memory_db()
    assert len(schema.pending(conn)) == len(schema.MIGRATIONS)
    schema.migrate(conn)
    assert schema.pending(conn) == []
    conn.close()


def test_analysis_cache_requires_a_score(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO analysis_cache (fen, depth, cp, mate, best_move, created_at)"
            " VALUES ('x', 1, NULL, NULL, 'e2e4', 'now')"
        )
