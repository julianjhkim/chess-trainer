"""Repository for ``cards``: the lazily grown opening tree.

A position is one card, keyed by EPD, so a transposition does not become a
second card. Dead ends (positions with too few master games) are kept as rows
with ``status='dead_end'`` so the "max depth reached" message has its stats and
the position is never fetched again.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from chess_trainer.db.connection import query_all, query_one, query_value, transaction

STATUS_ACTIVE = "active"
STATUS_DEAD_END = "dead_end"


@dataclass(frozen=True, slots=True)
class CardRow:
    epd: str
    fen: str
    line_uci: str
    depth: int
    side_to_move: str
    given_move_uci: str
    given_move_san: str
    status: str
    position_games: int
    queue_seq: int
    id: int | None = None
    parent_card_id: int | None = None
    mode: str | None = None
    answer_uci: str | None = None
    answer_san: str | None = None
    tied_ucis: tuple[str, ...] = ()
    opening_eco: str | None = None
    opening_name: str | None = None
    expanded_at: str | None = None
    created_at: str | None = None

    @property
    def is_dead_end(self) -> bool:
        return self.status == STATUS_DEAD_END

    @property
    def is_expanded(self) -> bool:
        return self.expanded_at is not None

    @property
    def ucis(self) -> tuple[str, ...]:
        return tuple(self.line_uci.split()) if self.line_uci.strip() else ()

    @property
    def opening_label(self) -> str | None:
        if self.opening_eco and self.opening_name:
            return f"{self.opening_eco} {self.opening_name}"
        return self.opening_name or None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row: sqlite3.Row) -> CardRow:
    raw_tied = row["tied_ucis"]
    tied: tuple[str, ...] = ()
    if raw_tied:
        try:
            parsed = json.loads(raw_tied)
            if isinstance(parsed, list):
                tied = tuple(str(x) for x in parsed)
        except ValueError:  # pragma: no cover - corrupted row
            tied = ()
    return CardRow(
        id=row["id"],
        epd=row["epd"],
        fen=row["fen"],
        line_uci=row["line_uci"],
        depth=row["depth"],
        parent_card_id=row["parent_card_id"],
        side_to_move=row["side_to_move"],
        given_move_uci=row["given_move_uci"],
        given_move_san=row["given_move_san"],
        status=row["status"],
        mode=row["mode"],
        answer_uci=row["answer_uci"],
        answer_san=row["answer_san"],
        tied_ucis=tied,
        opening_eco=row["opening_eco"],
        opening_name=row["opening_name"],
        position_games=row["position_games"],
        queue_seq=row["queue_seq"],
        expanded_at=row["expanded_at"],
        created_at=row["created_at"],
    )


def insert(conn: sqlite3.Connection, card: CardRow) -> CardRow:
    """Create a card. Returns the existing row if the position is already known."""
    with transaction(conn):
        existing = get_by_epd(conn, card.epd)
        if existing is not None:
            return existing
        conn.execute(
            """
            INSERT INTO cards (
                epd, fen, line_uci, depth, parent_card_id, side_to_move,
                given_move_uci, given_move_san, status, mode,
                answer_uci, answer_san, tied_ucis, opening_eco, opening_name,
                position_games, queue_seq, expanded_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card.epd,
                card.fen,
                card.line_uci,
                card.depth,
                card.parent_card_id,
                card.side_to_move,
                card.given_move_uci,
                card.given_move_san,
                card.status,
                card.mode,
                card.answer_uci,
                card.answer_san,
                json.dumps(list(card.tied_ucis)) if card.tied_ucis else None,
                card.opening_eco,
                card.opening_name,
                card.position_games,
                card.queue_seq,
                card.expanded_at,
                card.created_at or _now(),
            ),
        )
        stored = get_by_epd(conn, card.epd)
    assert stored is not None  # just inserted
    return stored


def get(conn: sqlite3.Connection, card_id: int) -> CardRow | None:
    row = query_one(conn, "SELECT * FROM cards WHERE id = ?", (card_id,))
    return _row(row) if row else None


def get_by_epd(conn: sqlite3.Connection, epd: str) -> CardRow | None:
    row = query_one(conn, "SELECT * FROM cards WHERE epd = ?", (epd,))
    return _row(row) if row else None


def children(conn: sqlite3.Connection, card_id: int) -> list[CardRow]:
    rows = query_all(
        conn,
        "SELECT * FROM cards WHERE parent_card_id = ? ORDER BY queue_seq",
        (card_id,),
    )
    return [_row(r) for r in rows]


def dead_end_children(conn: sqlite3.Connection, card_id: int) -> list[CardRow]:
    """Branches of a card that stopped for want of master games."""
    rows = query_all(
        conn,
        """
        SELECT * FROM cards
        WHERE parent_card_id = ? AND status = ?
        ORDER BY queue_seq
        """,
        (card_id, STATUS_DEAD_END),
    )
    return [_row(r) for r in rows]


def mark_expanded(conn: sqlite3.Connection, card_id: int) -> None:
    """Record that a card's branches have been created."""
    with transaction(conn):
        conn.execute(
            "UPDATE cards SET expanded_at = ? WHERE id = ? AND expanded_at IS NULL",
            (_now(), card_id),
        )


def max_queue_seq(conn: sqlite3.Connection) -> int:
    return int(query_value(conn, "SELECT COALESCE(MAX(queue_seq), 0) FROM cards", default=0))


def next_new_card(conn: sqlite3.Connection) -> CardRow | None:
    """The next card never answered before, in breadth-first order.

    A card is new when it has no scheduling row.
    """
    row = query_one(
        conn,
        """
        SELECT c.* FROM cards c
        LEFT JOIN card_schedule s ON s.card_id = c.id
        WHERE c.status = ? AND s.card_id IS NULL
        ORDER BY c.depth, c.queue_seq
        LIMIT 1
        """,
        (STATUS_ACTIVE,),
    )
    return _row(row) if row else None


def count_new(conn: sqlite3.Connection) -> int:
    return int(
        query_value(
            conn,
            """
            SELECT COUNT(*) FROM cards c
            LEFT JOIN card_schedule s ON s.card_id = c.id
            WHERE c.status = ? AND s.card_id IS NULL
            """,
            (STATUS_ACTIVE,),
            default=0,
        )
    )


def count(conn: sqlite3.Connection, status: str | None = None) -> int:
    if status is None:
        return int(query_value(conn, "SELECT COUNT(*) FROM cards", default=0))
    return int(
        query_value(conn, "SELECT COUNT(*) FROM cards WHERE status = ?", (status,), default=0)
    )


def has_any(conn: sqlite3.Connection) -> bool:
    return count(conn) > 0


def set_answer(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    mode: str,
    answer_uci: str,
    answer_san: str,
    tied_ucis: tuple[str, ...] | list[str] = (),
    position_games: int | None = None,
    opening_eco: str | None = None,
    opening_name: str | None = None,
) -> CardRow:
    """Record the answer resolved for a card the first time it is served.

    Branches are created with the game count their parent reported but without
    an answer, because deciding the answer needs the position's own record.
    """
    tied = tuple(tied_ucis)
    with transaction(conn):
        conn.execute(
            """
            UPDATE cards SET
                mode = ?,
                answer_uci = ?,
                answer_san = ?,
                tied_ucis = ?,
                position_games = COALESCE(?, position_games),
                opening_eco = COALESCE(?, opening_eco),
                opening_name = COALESCE(?, opening_name)
            WHERE id = ?
            """,
            (
                mode,
                answer_uci,
                answer_san,
                json.dumps(list(tied)) if tied else None,
                position_games,
                opening_eco,
                opening_name,
                card_id,
            ),
        )
        updated = get(conn, card_id)
    assert updated is not None
    return updated


def mark_dead_end(
    conn: sqlite3.Connection, card_id: int, *, position_games: int
) -> CardRow:
    """Turn a card into a dead end, when its own record proves it too thin."""
    with transaction(conn):
        conn.execute(
            "UPDATE cards SET status = ?, position_games = ? WHERE id = ?",
            (STATUS_DEAD_END, position_games, card_id),
        )
        updated = get(conn, card_id)
    assert updated is not None
    return updated


def needs_answer(card: CardRow) -> bool:
    """Whether a card still has to have its answer resolved."""
    return card.status == STATUS_ACTIVE and card.answer_uci is None
