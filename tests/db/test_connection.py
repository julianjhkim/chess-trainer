from __future__ import annotations

import sqlite3
import threading

import pytest

from chess_trainer.db import schema
from chess_trainer.db.connection import connect, open_memory_db, transaction


def test_connect_sets_row_factory(tmp_path):
    conn = connect(tmp_path / "x.db")
    row = conn.execute("SELECT 1 AS answer").fetchone()
    assert row["answer"] == 1
    conn.close()


def test_connect_creates_parent_directory(tmp_path):
    target = tmp_path / "deep" / "nested" / "x.db"
    conn = connect(target)
    conn.close()
    assert target.exists()


def test_connect_enables_wal_and_foreign_keys(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_transaction_commits_on_success(conn):
    with transaction(conn):
        conn.execute(
            "INSERT INTO app_state VALUES ('k', 'v', '2026-01-01T00:00:00+00:00')"
        )
    assert conn.execute("SELECT value FROM app_state WHERE key='k'").fetchone()[0] == "v"


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute(
                "INSERT INTO app_state VALUES ('k', 'v', '2026-01-01T00:00:00+00:00')"
            )
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM app_state").fetchone()[0] == 0


def test_nested_transaction_defers_to_the_outer_block(conn):
    with pytest.raises(RuntimeError):
        with transaction(conn):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO app_state VALUES ('k','v','2026-01-01T00:00:00+00:00')"
                )
            raise RuntimeError("outer fails after inner block finished")
    # The inner block must not have committed independently.
    assert conn.execute("SELECT COUNT(*) FROM app_state").fetchone()[0] == 0


def test_open_memory_db_is_usable():
    conn = open_memory_db()
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    conn.close()


def test_connection_carries_a_lock(db_path):
    conn = connect(db_path)
    assert conn.lock is not None
    conn.close()


def test_the_same_connection_works_from_another_thread(db_path):
    """A connection must survive crossing threads: FastAPI resolves sync
    dependencies in a threadpool, then may run the handler elsewhere."""
    conn = connect(db_path)
    results: list[int] = []

    def worker():
        results.append(conn.execute("SELECT 42").fetchone()[0])

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert results == [42]
    conn.close()


def test_concurrent_writes_from_many_threads_all_land(db_path):
    from datetime import date

    from chess_trainer.db import activity_repo

    conn = connect(db_path)
    barrier = threading.Barrier(5)

    def worker(day: int):
        barrier.wait()  # maximise the overlap
        activity_repo.record_step(conn, date(2026, 3, day))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(1, 6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(activity_repo.active_days(conn)) == 5
    conn.close()


def test_concurrent_transactions_do_not_collide(db_path):
    """Two threads opening transactions at once must serialise, not error."""
    from chess_trainer.db import state_repo

    conn = connect(db_path)
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker(n: int):
        barrier.wait()
        try:
            for i in range(5):
                state_repo.set(conn, f"key-{n}-{i}", str(i))
        except BaseException as exc:  # pragma: no cover - the point of the test
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert conn.execute("SELECT COUNT(*) FROM app_state").fetchone()[0] == 40
    conn.close()


def test_transaction_works_on_a_plain_connection_without_a_lock(tmp_path):
    """Repos must still work if handed a bare sqlite3.Connection."""
    plain = sqlite3.connect(tmp_path / "plain.db", isolation_level=None)
    plain.row_factory = sqlite3.Row
    plain.execute("CREATE TABLE t (x INTEGER)")
    with transaction(plain):
        plain.execute("INSERT INTO t VALUES (1)")
    assert plain.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    plain.close()


def test_concurrent_reads_and_writes_do_not_misuse_the_api(db_path):
    """Reads must be serialised too.

    Python's sqlite3 connection cannot be stepped by two threads at once: doing
    so raises ``InterfaceError: bad parameter or other API misuse``. This mixes
    readers and writers hard enough to catch a regression.
    """
    from datetime import date

    from chess_trainer.db import activity_repo, state_repo

    conn = connect(db_path)
    errors: list[BaseException] = []
    barrier = threading.Barrier(10)

    def writer(n: int):
        barrier.wait()
        try:
            for i in range(10):
                activity_repo.record_step(conn, date(2026, 4, 1 + (n * 10 + i) % 28))
                state_repo.set(conn, f"w{n}-{i}", str(i))
        except BaseException as exc:  # pragma: no cover - regression guard
            errors.append(exc)

    def reader():
        barrier.wait()
        try:
            for _ in range(30):
                activity_repo.active_days(conn)
                activity_repo.total_steps(conn)
                state_repo.get(conn, "missing")
        except BaseException as exc:  # pragma: no cover - regression guard
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
    threads += [threading.Thread(target=reader) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    conn.close()


def test_record_step_read_back_is_atomic(db_path):
    """record_step must report its own count, not one inflated by a racing writer."""
    from datetime import date

    from chess_trainer.db import activity_repo

    conn = connect(db_path)
    day = date(2026, 4, 15)
    counts: list[int] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def worker():
        barrier.wait()
        try:
            counts.append(activity_repo.record_step(conn, day).steps_completed)
        except BaseException as exc:  # pragma: no cover - regression guard
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Each caller saw a distinct, increasing count: no two read the same value.
    assert sorted(counts) == [1, 2, 3, 4, 5, 6]
    conn.close()
