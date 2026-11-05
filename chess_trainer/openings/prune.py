"""Bring cards grown under the old rules into line with ``repertoire``.

The tree used to grow both sides everywhere: every move with 5% branched, for
either colour. Now a card asks my move and branches only through its answer,
and the opponent's replies after it are the next cards, two plies down; only
my four White first moves also root a White side (``card_builder``).

This walks the tree the new way from its roots, using only rows already
there, and works out which cards belong and under which parent:

- the roots: every first-move card (my Black side) and, under each of my
  White first moves, the Black replies one ply down (my White side);
- under a card, the opponent's replies after its answer: rows already grown
  the new way (two plies down), plus the old rows under the answer's position
  (one ply down from it -- the old tree created exactly those replies);
- a dead-end answer stays, as the "max depth reached" note.

Everything else is deleted, schedules and review history with it; cards that
stay keep theirs, moved under their new parent. A card whose answer position
was never grown is marked unexpanded, so its next pass grows it the new way.
Idempotent: on a tree already in line it changes nothing. No network, no engine.
"""

from __future__ import annotations

import sqlite3

from chess_trainer.db import cards_repo
from chess_trainer.db.cards_repo import STATUS_ACTIVE, CardRow
from chess_trainer.openings import line as line_module
from chess_trainer.openings import repertoire


def prune(conn: sqlite3.Connection) -> int:
    """Prune the whole tree. Returns how many cards were deleted."""
    parent_of: dict[int, int | None] = {}
    regrow: set[int] = set()
    queue: list[CardRow] = []

    def want(card: CardRow, parent_id: int | None) -> None:
        if card.id is None or card.id in parent_of:
            return  # reached already (a transposition): keep the first parent
        parent_of[card.id] = parent_id
        if card.status == STATUS_ACTIVE:
            queue.append(card)

    for root in cards_repo.roots(conn):
        want(root, None)
        if not repertoire.black_only(root.ucis):
            for reply in cards_repo.children(conn, root.id or 0):
                if reply.depth == root.depth + 1:
                    want(reply, root.id)

    while queue:
        card = queue.pop(0)
        replies, grown = _replies(conn, card)
        for reply in replies:
            want(reply, card.id)
        if card.is_expanded and not grown:
            regrow.add(card.id or 0)

    for card_id, parent_id in parent_of.items():
        row = cards_repo.get(conn, card_id)
        if row is not None and row.parent_card_id != parent_id and parent_id is not None:
            cards_repo.reparent(conn, card_id, parent_id)
    for card_id in regrow:
        cards_repo.clear_expanded(conn, card_id)

    deleted = 0
    for card_id in _all_ids(conn):
        if card_id not in parent_of and cards_repo.get(conn, card_id) is not None:
            deleted += cards_repo.delete(conn, card_id)
    return deleted


def _replies(conn: sqlite3.Connection, card: CardRow) -> tuple[list[CardRow], bool]:
    """The rows that belong under a card, and whether its answer was grown.

    New-style rows hang two plies down. Old-style ones hang under the row for
    the answer's position (wherever that row sits: it may have been reached by
    another line first); a dead-end row there is kept itself, as the note.
    """
    replies = [
        c for c in cards_repo.children(conn, card.id or 0) if c.depth == card.depth + 2
    ]
    grown = bool(replies)
    if card.answer_uci is None:
        return replies, grown
    answer_epd = line_module.extend(
        line_module.position_of(card.ucis), card.answer_uci
    ).epd
    answer = cards_repo.get_by_epd(conn, answer_epd)
    if answer is None:
        return replies, grown
    if answer.status != STATUS_ACTIVE:
        if answer.parent_card_id == card.id:
            return [*replies, answer], True
        return replies, grown
    old = [
        c for c in cards_repo.children(conn, answer.id or 0)
        if c.depth == answer.depth + 1
    ]
    return [*replies, *old], grown or answer.is_expanded


def _all_ids(conn: sqlite3.Connection) -> list[int]:
    return [int(r[0]) for r in conn.execute("SELECT id FROM cards ORDER BY depth DESC")]
