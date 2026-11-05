"""Bring cards grown before the Black-only rule into line with it.

Lines that start with a first move I never play as White used to grow like any
other: every Black move with 5% became a branch, and White-to-move positions
were cards too. Under ``repertoire`` such a tree asks only Black's main moves,
so this removes what no longer belongs and keeps what does:

- a Black-to-move card keeps one branch, its answer; every other branch goes,
  with everything under it;
- the White-to-move card after the answer goes, but White's replies under it
  (the next Black-to-move cards) move up to the card before it, history and all;
- if that White-to-move card had not been expanded yet, the card before it is
  marked unexpanded, so its next pass grows the replies the new way.

A dead-end answer is kept, as the "max depth reached" note. Idempotent: on a
tree already in line it changes nothing. No network and no engine.
"""

from __future__ import annotations

import sqlite3

from chess_trainer.db import cards_repo
from chess_trainer.db.cards_repo import STATUS_ACTIVE, CardRow
from chess_trainer.openings import repertoire


def prune_black_only(conn: sqlite3.Connection) -> int:
    """Prune every Black-only tree. Returns how many cards were deleted."""
    deleted = 0
    for root in cards_repo.roots(conn):
        if repertoire.black_only(root.ucis):
            deleted += _prune(conn, root)
    return deleted


def _prune(conn: sqlite3.Connection, card: CardRow) -> int:
    """Prune under one Black-to-move card, then under the cards it keeps."""
    deleted = 0
    keep: list[CardRow] = []
    for child in cards_repo.children(conn, card.id or 0):
        if child.depth >= card.depth + 2:
            keep.append(child)  # a White reply, already grown the new way
        elif card.answer_uci is not None and child.given_move_uci == card.answer_uci:
            deleted_here, replies = _lift_replies(conn, card, child)
            deleted += deleted_here
            keep.extend(replies)
        else:
            deleted += cards_repo.delete(conn, child.id or 0)
    for child in keep:
        if child.status == STATUS_ACTIVE:
            deleted += _prune(conn, child)
    return deleted


def _lift_replies(
    conn: sqlite3.Connection, card: CardRow, answer: CardRow
) -> tuple[int, list[CardRow]]:
    """Replace the White-to-move card after ``card``'s answer by its children."""
    if answer.status != STATUS_ACTIVE:
        return 0, []  # too few games: stays as the dead-end note
    if not answer.is_expanded:
        cards_repo.clear_expanded(conn, card.id or 0)
        return cards_repo.delete(conn, answer.id or 0), []
    replies = cards_repo.children(conn, answer.id or 0)
    for reply in replies:
        cards_repo.reparent(conn, reply.id or 0, card.id or 0)
    return cards_repo.delete(conn, answer.id or 0), [
        cards_repo.get(conn, reply.id or 0) or reply for reply in replies
    ]
