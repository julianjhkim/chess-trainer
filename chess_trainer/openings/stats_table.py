"""The statistics table shown once a card has been answered.

One row per candidate move: the move, its share of the position's games, the
game count, the white/draw/black split and the average rating. The answer is
flagged, so is the most played move and Stockfish's own choice -- the question
only says *whether* those two agree, so the table is where you find out which
move each one was. A tie broken by the engine is noted.

Pure: built from a :class:`PositionStats` plus what the card decided.
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_trainer.explorer.explorer_types import PositionStats
from chess_trainer.openings.card_types import CardMode


@dataclass(frozen=True, slots=True)
class StatsRow:
    san: str
    uci: str
    games: int
    share: float
    white: int
    draws: int
    black: int
    average_rating: int | None
    #: The accepted answer for this card.
    is_answer: bool = False
    #: Stockfish's top move at the configured depth.
    is_engine_move: bool = False
    #: The move the masters played most often (every one of them, on a tie).
    is_most_played: bool = False
    #: One of several moves played equally often, resolved by the engine.
    is_tied: bool = False

    @property
    def white_percent(self) -> float:
        return 100.0 * self.white / self.games if self.games else 0.0

    @property
    def draw_percent(self) -> float:
        return 100.0 * self.draws / self.games if self.games else 0.0

    @property
    def black_percent(self) -> float:
        return 100.0 * self.black / self.games if self.games else 0.0


@dataclass(frozen=True, slots=True)
class StatsTable:
    rows: list[StatsRow]
    total_games: int
    mode: CardMode | None
    #: Set when several moves were played equally often.
    tie_note: str | None = None
    #: Set when the card was answered by the engine rather than by frequency.
    engine_note: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.rows


def build(
    stats: PositionStats,
    *,
    answer_uci: str | None,
    mode: CardMode | None,
    tied_ucis: tuple[str, ...] | list[str] = (),
    engine_move_uci: str | None = None,
    engine_move_san: str | None = None,
) -> StatsTable:
    """Build the table for a position.

    ``engine_move_uci`` is Stockfish's top move, whatever the mode: on a
    frequency card the question has already said whether it matched the most
    played move, and this is where that claim can be checked.
    """
    total = stats.total_games
    tied = set(tied_ucis)
    # An engine-mode card is answered by the engine, so its answer is the
    # engine's move even when the caller did not say so separately.
    engine_uci = engine_move_uci or (answer_uci if mode is CardMode.ENGINE else None)
    ordered = stats.by_games()
    most_played = ordered[0].games if ordered else 0
    rows = [
        StatsRow(
            san=move.san,
            uci=move.uci,
            games=move.games,
            share=move.share_of(total),
            white=move.white,
            draws=move.draws,
            black=move.black,
            average_rating=move.average_rating,
            is_answer=move.uci == answer_uci,
            is_engine_move=move.uci == engine_uci,
            is_most_played=move.games == most_played and move.games > 0,
            is_tied=move.uci in tied,
        )
        for move in ordered
    ]

    # An engine-mode answer need not appear in the database at all, and nor need
    # Stockfish's choice on a frequency card. Both are named to the player, so
    # both get a row rather than being left nowhere to be found.
    extra: list[tuple[str, str | None]] = []
    if mode is CardMode.ENGINE and answer_uci is not None:
        extra.append((answer_uci, None))
    if engine_uci is not None and engine_uci != answer_uci:
        extra.append((engine_uci, engine_move_san))

    for uci, san in extra:
        if any(row.uci == uci for row in rows):
            continue
        rows.append(
            StatsRow(
                san=san or uci,
                uci=uci,
                games=0,
                share=0.0,
                white=0,
                draws=0,
                black=0,
                average_rating=None,
                is_answer=uci == answer_uci,
                is_engine_move=uci == engine_uci,
            )
        )

    return StatsTable(
        rows=rows,
        total_games=total,
        mode=mode,
        tie_note=_tie_note(tied, rows),
        engine_note=_engine_note(mode, total),
    )


def _tie_note(tied: set[str], rows: list[StatsRow]) -> str | None:
    if len(tied) < 2:
        return None
    sans = [row.san for row in rows if row.uci in tied]
    joined = ", ".join(sans)
    return (
        f"{len(tied)} moves are played equally often ({joined}); "
        "Stockfish picked between them."
    )


def _engine_note(mode: CardMode | None, total_games: int) -> str | None:
    if mode is not CardMode.ENGINE:
        return None
    return (
        f"Only {total_games} master game{'s' if total_games != 1 else ''} here, "
        "so Stockfish decides rather than frequency."
    )
