"""Growing the card tree, lazily.

Nothing is prebuilt. Two moments do the work:

*Expansion* happens when a card is first answered correctly. The card's own
cached explorer record already says how often each branch move was played, and
the number of games that played a move from a position is exactly the number
that reached the position after it -- so every child row, including whether it
is a dead end, is created without a single extra request. The opening name for
each child comes from the same record.

*Preparation* happens the first time a card is served. Only then is the child
position's own record fetched, because only then is its answer needed. So a
request is spent per card actually drilled, not per card created.

The root is the exception the spec calls for: not a card itself, but every one
of White's first moves branches from it with no 5% filter.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from chess_trainer.db import cards_repo
from chess_trainer.db.cards_repo import (
    STATUS_ACTIVE,
    STATUS_DEAD_END,
    CardRow,
)
from chess_trainer.engine import best_move as best_move_module
from chess_trainer.engine.stockfish import Analyser
from chess_trainer.explorer import cache as explorer_cache
from chess_trainer.explorer.cache import MastersSource
from chess_trainer.explorer.explorer_types import Opening, PositionStats
from chess_trainer.openings import line as line_module
from chess_trainer.openings import queue_order, tree_rules
from chess_trainer.openings.card_types import Branch, CardMode, CardPlan
from chess_trainer.openings.line import LinePosition


@dataclass(frozen=True, slots=True)
class PreparedCard:
    """A card with its answer resolved and its explorer record to hand."""

    card: CardRow
    stats: PositionStats
    #: True when this call had to resolve the answer (first time served).
    resolved_now: bool = False


@dataclass(frozen=True, slots=True)
class ExpansionResult:
    """What creating a card's branches produced."""

    new_cards: list[CardRow] = field(default_factory=list)
    dead_ends: list[CardRow] = field(default_factory=list)
    already_expanded: bool = False

    @property
    def created(self) -> int:
        return len(self.new_cards) + len(self.dead_ends)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- reading the explorer -------------------------------------------------
def stats_for_position(
    conn: sqlite3.Connection,
    source: MastersSource,
    position: LinePosition,
    *,
    use_cache: bool = True,
) -> PositionStats:
    """The explorer's record for a position, through the cache."""
    payload = explorer_cache.fetch(
        conn, source, fen=position.fen, epd=position.epd, use_cache=use_cache
    )
    return PositionStats.of(payload)


def stats_for_card(
    conn: sqlite3.Connection, source: MastersSource, card: CardRow
) -> PositionStats:
    position = line_module.position_of(card.ucis)
    return stats_for_position(conn, source, position)


def cached_stats_for_card(
    conn: sqlite3.Connection, card: CardRow
) -> PositionStats | None:
    """The card's record if it is already cached, without any network use."""
    payload = explorer_cache.cached_only(conn, card.epd)
    return PositionStats.of(payload) if payload is not None else None


# -- bootstrap ------------------------------------------------------------
def ensure_bootstrapped(
    conn: sqlite3.Connection, source: MastersSource
) -> list[CardRow]:
    """Create the depth-1 cards: one per White first move.

    The start position is not a card, and its branches take no 5% filter.
    Already-bootstrapped databases are left alone.
    """
    if cards_repo.has_any(conn):
        return []

    root = line_module.root()
    stats = stats_for_position(conn, source, root)
    plan = tree_rules.plan_root(stats)
    return _create_children(conn, parent=None, parent_position=root, plan=plan, stats=stats)


# -- preparation ----------------------------------------------------------
def prepare_card(
    conn: sqlite3.Connection,
    source: MastersSource,
    engine: Analyser,
    card: CardRow,
    *,
    engine_depth: int,
) -> PreparedCard:
    """Make a card ready to serve, resolving its answer the first time.

    A card whose own record turns out to be too thin becomes a dead end, which
    can happen when the parent's game count and the position's own disagree.
    """
    stats = stats_for_card(conn, source, card)

    if not cards_repo.needs_answer(card):
        return PreparedCard(card=card, stats=stats, resolved_now=False)

    plan = tree_rules.plan_position(stats)

    if not plan.is_card:
        updated = cards_repo.mark_dead_end(
            conn, card.id or 0, position_games=plan.total_games
        )
        return PreparedCard(card=updated, stats=stats, resolved_now=True)

    answer_uci, tied = _resolve_answer(
        conn, engine, card, stats, plan, engine_depth=engine_depth
    )
    opening = stats.opening
    updated = cards_repo.set_answer(
        conn,
        card.id or 0,
        mode=(plan.mode or CardMode.FREQUENCY).value,
        answer_uci=answer_uci,
        answer_san=line_module.san_of(card.fen, answer_uci),
        tied_ucis=tied,
        position_games=plan.total_games,
        opening_eco=opening.eco if opening else None,
        opening_name=opening.name if opening else None,
    )
    return PreparedCard(card=updated, stats=stats, resolved_now=True)


def _resolve_answer(
    conn: sqlite3.Connection,
    engine: Analyser,
    card: CardRow,
    stats: PositionStats,
    plan: CardPlan,
    *,
    engine_depth: int,
) -> tuple[str, tuple[str, ...]]:
    """The accepted move for a card, and the tie it resolved (if any)."""
    if plan.mode is CardMode.ENGINE:
        chosen = best_move_module.best_move(conn, engine, card.fen, engine_depth)
        if chosen is None:  # pragma: no cover - a card position is never terminal
            raise ValueError(f"No legal move in {card.fen}")
        return chosen, ()

    candidates = plan.answer_candidates
    if not candidates:  # pragma: no cover - plan_position guarantees at least one
        raise ValueError(f"No candidate moves for {card.epd}")
    if len(candidates) == 1:
        return candidates[0], ()

    # Several moves played exactly as often: Stockfish picks between them.
    chosen = best_move_module.best_among(
        conn, engine, card.fen, engine_depth, list(candidates)
    )
    return chosen, tuple(candidates)


# -- expansion ------------------------------------------------------------
def expand_card(
    conn: sqlite3.Connection,
    source: MastersSource,
    engine: Analyser,
    card: CardRow,
    *,
    engine_depth: int,
) -> ExpansionResult:
    """Create a card's branches. Called on its first correct answer.

    Uses the card's cached record, so no request is needed for the children.
    """
    if card.is_expanded:
        return ExpansionResult(already_expanded=True)
    if card.status != STATUS_ACTIVE:
        return ExpansionResult(already_expanded=True)

    stats = stats_for_card(conn, source, card)
    plan = tree_rules.plan_position(stats)

    if plan.mode is CardMode.ENGINE:
        # One branch only: the position after the engine's move, which is this
        # card's answer.
        answer = card.answer_uci or _resolve_answer(
            conn, engine, card, stats, plan, engine_depth=engine_depth
        )[0]
        branches = tree_rules.engine_branch(answer, stats)
    else:
        branches = plan.branches

    position = line_module.position_of(card.ucis)
    created = _create_children(
        conn, parent=card, parent_position=position, plan=plan, stats=stats, branches=branches
    )
    cards_repo.mark_expanded(conn, card.id or 0)

    return ExpansionResult(
        new_cards=[c for c in created if c.status == STATUS_ACTIVE],
        dead_ends=[c for c in created if c.status == STATUS_DEAD_END],
    )


def _create_children(
    conn: sqlite3.Connection,
    *,
    parent: CardRow | None,
    parent_position: LinePosition,
    plan: CardPlan,
    stats: PositionStats,
    branches: tuple[Branch, ...] | None = None,
) -> list[CardRow]:
    """Create one row per branch, in game-count order.

    A branch's game count is its child position's total, so a dead end is
    recognised here without fetching the child.
    """
    chosen = plan.branches if branches is None else branches
    if not chosen:
        return []

    start = queue_order.next_sequence(cards_repo.max_queue_seq(conn))
    created: list[CardRow] = []

    for branch, sequence in queue_order.assign_sequences(chosen, start=start):
        child_position = line_module.extend(parent_position, branch.uci)
        opening = _child_opening(stats, branch.uci)
        status = (
            STATUS_ACTIVE if branch.games >= tree_rules.MIN_GAMES else STATUS_DEAD_END
        )
        created.append(
            cards_repo.insert(
                conn,
                CardRow(
                    epd=child_position.epd,
                    fen=child_position.fen,
                    line_uci=child_position.line_uci,
                    depth=child_position.depth,
                    parent_card_id=parent.id if parent else None,
                    side_to_move=child_position.side_to_move,
                    given_move_uci=branch.uci,
                    given_move_san=line_module.san_of(parent_position.fen, branch.uci),
                    status=status,
                    position_games=branch.games,
                    queue_seq=sequence,
                    opening_eco=opening.eco if opening else None,
                    opening_name=opening.name if opening else None,
                    created_at=_now(),
                ),
            )
        )
    return created


def _child_opening(stats: PositionStats, uci: str) -> Opening | None:
    """The opening of the position after ``uci``, as the parent's record says."""
    move = stats.move(uci)
    return move.opening if move is not None else None
