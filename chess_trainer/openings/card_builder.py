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

Lines that start with a first move I never play as White are grown for Black
only (``repertoire``): a card branches only through its answer, and the
White-to-move position after it is not a card -- White's replies branch from
it straight to the next Black-to-move cards. That position's own record is
needed for those replies, so such an expansion costs one request.
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
from chess_trainer.openings import queue_order, repertoire, tree_rules
from chess_trainer.openings.card_types import Branch, CardMode, CardPlan
from chess_trainer.openings.line import LinePosition


@dataclass(frozen=True, slots=True)
class PreparedCard:
    """A card with its answer resolved and its explorer record to hand."""

    card: CardRow
    stats: PositionStats
    #: True when this call had to resolve the answer (first time served).
    resolved_now: bool = False
    #: Stockfish's top move here, resolved before the card is shown.
    engine_best_uci: str | None = None


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

    Stockfish's own top move is resolved here too, so the question can say
    whether the most played move is also the engine's without pausing the card
    to find out. It costs nothing after the first time: the result is cached by
    position and depth.
    """
    stats = stats_for_card(conn, source, card)

    if not cards_repo.needs_answer(card):
        return PreparedCard(
            card=card,
            stats=stats,
            resolved_now=False,
            engine_best_uci=engine_best_move(
                conn, engine, card, engine_depth=engine_depth
            ),
        )

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
    return PreparedCard(
        card=updated,
        stats=stats,
        resolved_now=True,
        engine_best_uci=engine_best_move(
            conn, engine, updated, engine_depth=engine_depth
        ),
    )


def engine_best_move(
    conn: sqlite3.Connection,
    engine: Analyser,
    card: CardRow,
    *,
    engine_depth: int,
) -> str | None:
    """Stockfish's top move in a card's position, through the analysis cache.

    ``None`` for a dead end, which is never asked and so never searched.
    """
    if card.status != STATUS_ACTIVE:
        return None
    return best_move_module.best_move(conn, engine, card.fen, engine_depth)


def opening_before(conn: sqlite3.Connection, card: CardRow) -> str | None:
    """The opening name of the position the arrow move is played from.

    Usually the parent card's position (its name already inherited if Lichess
    gives it none); a first move starts from the unnamed start position. In a
    Black-only line the parent is two moves back, and the arrow is played from
    the position after the parent's answer.
    """
    if card.parent_card_id is None:
        return None
    parent = cards_repo.get(conn, card.parent_card_id)
    if parent is None:
        return None
    if card.depth > parent.depth + 1:
        stats = cached_stats_for_card(conn, parent)
        return opening_after(stats, parent) if stats is not None else parent.opening_label
    return parent.opening_label


def opening_after(stats: PositionStats, card: CardRow) -> str | None:
    """The opening name of the position after the answer, as Lichess shows it.

    The position's own book name if the card's record gives one for the
    answer move, else the card's name carries on.
    """
    move = stats.move(card.answer_uci) if card.answer_uci else None
    if move is not None and move.opening is not None:
        return move.opening.label
    return card.opening_label


def engine_agrees(card: CardRow, engine_best_uci: str | None) -> bool | None:
    """Whether a card's answer is also Stockfish's top move.

    Only frequency-mode cards have anything to compare: there the answer is the
    move the masters played most, which the engine may well disagree with, and
    saying so turns the card into a fair question rather than a trap. An
    engine-mode card is answered *by* the engine, so the question never arises.

    ``None`` means there is nothing to say. The caller must not turn it into a
    "no": it is also what an unanswered card and a missing engine result give.
    """
    if card.mode != CardMode.FREQUENCY.value:
        return None
    if card.answer_uci is None or engine_best_uci is None:
        return None
    return engine_best_uci == card.answer_uci


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

    if repertoire.black_only(card.ucis):
        return _expand_black_only(
            conn, source, engine, card, stats, plan, engine_depth=engine_depth
        )

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


def _expand_black_only(
    conn: sqlite3.Connection,
    source: MastersSource,
    engine: Analyser,
    card: CardRow,
    stats: PositionStats,
    plan: CardPlan,
    *,
    engine_depth: int,
) -> ExpansionResult:
    """Branch a Black-only card through its answer and White's replies.

    The answer's position is White to move and never a card. If too few games
    reach it, it is kept as a dead end ("max depth reached"); otherwise its own
    record decides White's replies by the usual rules (every move with 5% when
    there are 20+ games, else the engine's move), and each reply is a new card.
    """
    answer = card.answer_uci or _resolve_answer(
        conn, engine, card, stats, plan, engine_depth=engine_depth
    )[0]
    position = line_module.position_of(card.ucis)
    answer_branch = tree_rules.engine_branch(answer, stats)

    if answer_branch[0].games < tree_rules.MIN_GAMES:
        created = _create_children(
            conn, parent=card, parent_position=position, plan=plan, stats=stats,
            branches=answer_branch,
        )
    else:
        after = line_module.extend(position, answer)
        after_stats = stats_for_position(conn, source, after)
        after_plan = tree_rules.plan_position(after_stats)
        if not after_plan.is_card:
            dead = Branch(
                uci=answer, games=after_plan.total_games, share=answer_branch[0].share
            )
            created = _create_children(
                conn, parent=card, parent_position=position, plan=plan, stats=stats,
                branches=(dead,), dead_ends=True,
            )
        else:
            if after_plan.mode is CardMode.ENGINE:
                best = best_move_module.best_move(conn, engine, after.fen, engine_depth)
                replies = tree_rules.engine_branch(best, after_stats) if best else ()
            else:
                replies = after_plan.branches
            inherited = (
                after_stats.opening or _child_opening(stats, answer) or _opening_of(card)
            )
            created = _create_children(
                conn, parent=card, parent_position=after, plan=after_plan,
                stats=after_stats, branches=replies, inherited=inherited,
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
    inherited: Opening | None = None,
    dead_ends: bool = False,
) -> list[CardRow]:
    """Create one row per branch, in game-count order.

    A branch's game count is its child position's total, so a dead end is
    recognised here without fetching the child. ``inherited`` is the name a
    child the record does not name takes (the parent's, unless given);
    ``dead_ends`` makes every row a dead end whatever its count.
    """
    chosen = plan.branches if branches is None else branches
    if not chosen:
        return []

    start = queue_order.next_sequence(cards_repo.max_queue_seq(conn))
    created: list[CardRow] = []

    for branch, sequence in queue_order.assign_sequences(chosen, start=start):
        child_position = line_module.extend(parent_position, branch.uci)
        opening = _child_opening(stats, branch.uci) or inherited or _opening_of(parent)
        status = (
            STATUS_ACTIVE
            if branch.games >= tree_rules.MIN_GAMES and not dead_ends
            else STATUS_DEAD_END
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


def _opening_of(card: CardRow | None) -> Opening | None:
    """A card's opening, inherited by a child the explorer gives no name.

    Lichess names only exact book positions (1.e3 is the Van't Kruijs Opening,
    1.e3 d5 has no name of its own), so like Lichess's own board a nameless
    position keeps the name of the line it came from. Should the position's
    own record name it later, that name wins (``set_answer`` keeps a stored
    name only when the record has none).
    """
    if card is None or not card.opening_name:
        return None
    return Opening(eco=card.opening_eco or "", name=card.opening_name)
