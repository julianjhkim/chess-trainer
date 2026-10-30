"""The rules that turn a position's master-game record into a card.

Pure: hand it a :class:`PositionStats` and it says whether the position is a
card, how its answer is decided, and which moves branch from it. The engine is
never called here -- the rules only report *that* a search is needed (to break a
tie, or to answer an engine-mode card), and the builder performs it.

    | games | correct answer                                   | branches               |
    |-------|--------------------------------------------------|------------------------|
    | >= 20 | most frequent move; tie -> Stockfish among tied   | every move with >= 5%  |
    | 5-19  | Stockfish's top move                              | the engine move only   |
    | < 5   | not a card, the line stops                        | none                   |

The start position is the exception: it is not a card, and *all* of White's
first moves branch from it, with no 5% filter, ordered by game count.
"""

from __future__ import annotations

from chess_trainer.explorer.explorer_types import PositionStats
from chess_trainer.openings.card_types import Branch, CardMode, CardPlan, CardStatus

#: At or above this many games, frequency is trusted.
FREQUENCY_THRESHOLD = 20

#: Below this many games the position is not a card and the line stops.
MIN_GAMES = 5

#: A move needs this share of a position's games to become a branch.
BRANCH_SHARE_PERCENT = 5.0


def branches_by_frequency(
    stats: PositionStats, *, min_share: float = BRANCH_SHARE_PERCENT
) -> tuple[Branch, ...]:
    """Moves with at least ``min_share`` percent of the games, most played first."""
    total = stats.total_games
    return tuple(
        Branch(uci=move.uci, games=move.games, share=move.share_of(total))
        for move in stats.by_games()
        if move.share_of(total) >= min_share
    )


def all_branches(stats: PositionStats) -> tuple[Branch, ...]:
    """Every move the database has, most played first and no share filter."""
    total = stats.total_games
    return tuple(
        Branch(uci=move.uci, games=move.games, share=move.share_of(total))
        for move in stats.by_games()
    )


def most_frequent_candidates(stats: PositionStats) -> tuple[str, ...]:
    """The most-played move, or every move tied for most played.

    More than one means the engine has to choose between them.
    """
    ordered = stats.by_games()
    if not ordered:
        return ()
    best = ordered[0].games
    return tuple(move.uci for move in ordered if move.games == best)


def plan_root(stats: PositionStats) -> CardPlan:
    """The start position: not a card, but every first move branches from it."""
    return CardPlan(
        total_games=stats.total_games,
        status=CardStatus.ACTIVE,
        mode=None,
        answer_candidates=(),
        branches=all_branches(stats),
        is_root=True,
    )


def plan_position(stats: PositionStats, *, is_root: bool = False) -> CardPlan:
    """Decide what a position is, from its master-game record."""
    if is_root:
        return plan_root(stats)

    total = stats.total_games

    if total < MIN_GAMES:
        return CardPlan(total_games=total, status=CardStatus.DEAD_END)

    if not stats.moves:
        # Enough games reached here, but the database records no continuation
        # (the games all ended here). Nothing can be asked, so the line stops.
        return CardPlan(total_games=total, status=CardStatus.DEAD_END)

    if total >= FREQUENCY_THRESHOLD:
        return CardPlan(
            total_games=total,
            status=CardStatus.ACTIVE,
            mode=CardMode.FREQUENCY,
            answer_candidates=most_frequent_candidates(stats),
            branches=branches_by_frequency(stats),
        )

    # 5-19 games: too thin to trust frequency, so the engine answers and the
    # only branch is the position after its move.
    return CardPlan(
        total_games=total,
        status=CardStatus.ACTIVE,
        mode=CardMode.ENGINE,
        answer_candidates=(),
        branches=(),
    )


def engine_branch(uci: str, stats: PositionStats) -> tuple[Branch, ...]:
    """The single branch of an engine-mode card: the engine's own move.

    The move may not appear in the database at all, in which case it has no
    game count of its own.
    """
    move = stats.move(uci)
    games = move.games if move is not None else 0
    share = move.share_of(stats.total_games) if move is not None else 0.0
    return (Branch(uci=uci, games=games, share=share),)


def describe_threshold(total_games: int) -> str:
    """A short explanation of why a position is treated the way it is."""
    if total_games < MIN_GAMES:
        return f"only {total_games} master game{'s' if total_games != 1 else ''}"
    if total_games < FREQUENCY_THRESHOLD:
        return f"{total_games} master games, too few to trust frequency"
    return f"{total_games} master games"
