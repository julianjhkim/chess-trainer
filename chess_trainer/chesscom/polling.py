"""Waiting for a game that has just finished to appear in the archive.

The chess.com archive can lag by a minute or two after a game ends, so step 2
polls for something newer than the last game we saw. Both the clock and the
sleep are injectable, so the retry behaviour is tested without real waiting.

The network call is passed in as ``fetch_games``, which keeps the retry loop
itself free of HTTP.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from chess_trainer.chesscom.client import ChessComError, PlayerNotFound
from chess_trainer.chesscom.game_model import ChessComGame
from chess_trainer.chesscom.latest_game import most_recent, newer_than

#: Total time the whole step-2 fetch should keep trying, per the spec (~2 min).
TOTAL_BUDGET_SECONDS = 120.0

#: How long one server-side polling window lasts. The client repeats these
#: windows until the total budget is spent, so the UI can report progress
#: instead of hanging on a single two-minute request.
WINDOW_SECONDS = 12.0

#: Gap between archive fetches inside a window.
INTERVAL_SECONDS = 3.0

FetchGames = Callable[[], list[ChessComGame]]


@dataclass(frozen=True, slots=True)
class PollResult:
    """What one polling window found."""

    game: ChessComGame | None
    attempts: int
    waited: float
    #: Set when every attempt failed with a transient error.
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.game is not None


def poll_for_new_game(
    fetch_games: FetchGames,
    *,
    last_seen_id: str | None,
    last_seen_end_time: int | None = None,
    budget_seconds: float = WINDOW_SECONDS,
    interval_seconds: float = INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> PollResult:
    """Look for a game newer than ``last_seen_id`` until the budget runs out.

    Transient chess.com failures are retried within the budget rather than
    aborting the window; a bad username is not transient and propagates.
    """
    started = monotonic()
    attempts = 0
    last_error: str | None = None

    while True:
        attempts += 1
        try:
            games = fetch_games()
        except PlayerNotFound:
            raise
        except ChessComError as exc:
            last_error = str(exc)
        else:
            last_error = None
            candidates = newer_than(games, last_seen_id, last_seen_end_time)
            newest = most_recent(candidates)
            if newest is not None:
                return PollResult(
                    game=newest, attempts=attempts, waited=monotonic() - started
                )

        elapsed = monotonic() - started
        if elapsed + interval_seconds >= budget_seconds:
            return PollResult(
                game=None, attempts=attempts, waited=elapsed, error=last_error
            )
        sleep(interval_seconds)
