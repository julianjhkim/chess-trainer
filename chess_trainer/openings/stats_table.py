"""The statistics table shown once a card has been answered.

One row per candidate move: the move, its share of the position's games, the
game count, the white/draw/black split and the average rating. The answer is
flagged, the engine's move is flagged when the card is in engine mode, and a
tie broken by the engine is noted.

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
    #: Marked when the card is in engine mode, per the spec.
    is_engine_move: bool = False
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
) -> StatsTable:
    """Build the table for a position."""
    total = stats.total_games
    tied = set(tied_ucis)
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
            is_engine_move=(
                mode is CardMode.ENGINE and move.uci == (engine_move_uci or answer_uci)
            ),
            is_tied=move.uci in tied,
        )
        for move in stats.by_games()
    ]

    # An engine-mode answer need not appear in the database at all.
    if (
        mode is CardMode.ENGINE
        and answer_uci is not None
        and not any(row.uci == answer_uci for row in rows)
    ):
        rows.append(
            StatsRow(
                san=answer_uci,
                uci=answer_uci,
                games=0,
                share=0.0,
                white=0,
                draws=0,
                black=0,
                average_rating=None,
                is_answer=True,
                is_engine_move=True,
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
