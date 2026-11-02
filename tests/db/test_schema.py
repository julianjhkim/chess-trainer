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


def test_engine_lines_and_hints_have_columns(conn):
    analysis_columns = {row[1] for row in conn.execute("PRAGMA table_info(analysis_cache)")}
    review_columns = {row[1] for row in conn.execute("PRAGMA table_info(game_reviews)")}
    assert "pv" in analysis_columns
    assert "used_hint" in review_columns


def test_a_version_3_database_upgrades_in_place():
    conn = open_memory_db()
    for migration in schema.MIGRATIONS[:3]:
        conn.executescript(migration.sql)
    conn.execute("PRAGMA user_version = 3")
    conn.execute(
        "INSERT INTO analysis_cache (fen, depth, cp, mate, best_move, created_at)"
        " VALUES ('x', 20, 10, NULL, 'e2e4', 'now')"
    )
    applied = schema.migrate(conn)
    assert [m.version for m in applied] == [4, 5, 6, 7]
    row = conn.execute("SELECT pv FROM analysis_cache WHERE fen = 'x'").fetchone()
    assert row[0] is None
    conn.close()


def _card(conn, card_id, parent, line, eco=None, name=None):
    conn.execute(
        "INSERT INTO cards (id, epd, fen, line_uci, depth, parent_card_id,"
        " side_to_move, given_move_uci, given_move_san, status, position_games,"
        " queue_seq, opening_eco, opening_name, created_at)"
        " VALUES (?, ?, 'fen', ?, ?, ?, 'white', 'a1a2', 'x', 'active', 100, ?,"
        " ?, ?, 'now')",
        (card_id, f"epd{card_id}", line, line.count(" ") + 1, parent, card_id, eco, name),
    )


def test_unnamed_opening_cards_take_the_nearest_named_ancestors_name():
    conn = open_memory_db()
    for migration in schema.MIGRATIONS[:6]:
        conn.executescript(migration.sql)
    conn.execute("PRAGMA user_version = 6")
    _card(conn, 1, None, "e2e3", "A00", "Van't Kruijs Opening")
    _card(conn, 2, 1, "e2e3 d7d5")
    _card(conn, 3, 2, "e2e3 d7d5 g1f3")
    _card(conn, 4, 3, "e2e3 d7d5 g1f3 c7c5", "A13", "Named Here")
    _card(conn, 5, None, "h2h4")
    schema.migrate(conn)
    names = dict(conn.execute("SELECT id, opening_eco || ' ' || opening_name FROM cards"))
    assert names == {
        1: "A00 Van't Kruijs Opening",
        2: "A00 Van't Kruijs Opening",
        3: "A00 Van't Kruijs Opening",
        4: "A13 Named Here",
        5: None,
    }
    conn.close()
