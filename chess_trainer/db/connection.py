"""SQLite connection management.

A single module owns how connections are opened so every caller gets the same
pragmas, row factory and transaction semantics.

Threading
---------
The app hands blocking work (engine searches) to worker threads, FastAPI
resolves synchronous dependencies in its own threadpool, and the frontend fires
several requests at once on load, so a connection is routinely touched from more
than one thread. Rather than juggle one connection per thread -- which makes it
easy to leak a connection from the thread that created it into the thread that
uses it -- there is one connection, opened with ``check_same_thread=False`` and
carrying an :class:`~threading.RLock`.

Python's ``sqlite3`` connection cannot be used concurrently even when SQLite
itself is threadsafe: two threads stepping statements on one connection raises
``InterfaceError``. So *every* access is serialised, not just writes. Callers go
through :func:`query_one`, :func:`query_all`, :func:`execute` and
:func:`transaction`, each of which holds the lock across both the execute and
the fetch. The lock is reentrant, so a query inside a transaction is fine. For a
single-user local app it is effectively uncontended.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

#: Passed to ``sqlite3.connect`` for in-memory databases in tests.
MEMORY = ":memory:"


class TrainerConnection(sqlite3.Connection):
    """A connection that carries the lock guarding its transactions.

    ``sqlite3.Connection`` does not accept arbitrary attributes, so the lock
    lives on this subclass, installed via ``connect(factory=...)``.
    """

    lock: threading.RLock


def connect(db_path: Path | str) -> TrainerConnection:
    """Open a connection with the pragmas this app relies on.

    * ``Row`` factory so rows are addressable by column name.
    * WAL journalling, so a long engine analysis never blocks a read.
    * Foreign keys on, which SQLite otherwise leaves off.
    * ``isolation_level=None``: transactions are managed explicitly via
      :func:`transaction` rather than by implicit commits.
    """
    target = str(db_path)
    if target != MEMORY:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        target = str(path)

    conn = sqlite3.connect(
        target,
        isolation_level=None,
        check_same_thread=False,
        factory=TrainerConnection,
    )
    conn.lock = threading.RLock()
    conn.row_factory = sqlite3.Row
    if target != MEMORY:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def locked(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Hold the connection's lock, if it has one.

    A plain ``sqlite3.Connection`` (handed in by a test, say) has no lock and
    passes straight through.
    """
    lock = getattr(conn, "lock", None)
    if lock is None:
        yield conn
        return
    with lock:
        yield conn


def query_one(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> sqlite3.Row | None:
    """Run a query and fetch a single row, all under the lock."""
    with locked(conn):
        return conn.execute(sql, params).fetchone()


def query_all(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> list[sqlite3.Row]:
    """Run a query and fetch every row, all under the lock."""
    with locked(conn):
        return conn.execute(sql, params).fetchall()


def query_value(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] = (),
    default: object = None,
) -> object:
    """Run a query and return the first column of the first row."""
    row = query_one(conn, sql, params)
    return default if row is None else row[0]


def execute(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> None:
    """Run a statement for its side effect, under the lock."""
    with locked(conn):
        conn.execute(sql, params)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in a transaction, committing on success and rolling back on error.

    Holds the connection's lock for the duration, so two threads cannot open
    overlapping transactions on the same connection. Nested use is safe: if a
    transaction is already open this is a passthrough, and the outermost block
    decides the outcome.
    """
    with locked(conn):
        with _transaction_body(conn) as c:
            yield c


@contextmanager
def _transaction_body(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def open_memory_db() -> TrainerConnection:
    """A fresh in-memory database; convenient for tests."""
    return connect(MEMORY)
