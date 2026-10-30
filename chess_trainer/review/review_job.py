"""Running a review in the background so the UI can show progress.

Analysing a game at depth 20 takes a second or so per move of mine, and the
first inaccuracy might be the last move played -- which on a long game is a
minute or more. Rather than block a request for that long, the analysis runs in
a worker thread and the browser polls this job for progress.

The job owns the thread; the resulting :class:`ReviewSession` owns the
interaction once the analysis is done.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from enum import Enum

from chess_trainer.db.games_repo import StoredGame
from chess_trainer.engine.stockfish import Analyser
from chess_trainer.pgn.parse import ParsedGame
from chess_trainer.review.review_session import (
    ReviewSession,
    build_review,
    count_my_moves,
)


class ReviewStatus(str, Enum):
    ANALYSING = "analysing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewCancelled(Exception):
    """Raised inside the worker thread to abandon an analysis in progress."""


@dataclass(slots=True)
class ReviewJob:
    """One game review: its analysis progress, then its interactive session."""

    game: StoredGame
    parsed: ParsedGame
    my_colour: str
    depth: int
    total_moves: int
    status: ReviewStatus = ReviewStatus.ANALYSING
    assessed: int = 0
    error: str | None = None
    session: ReviewSession | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    @property
    def is_ready(self) -> bool:
        return self.status is ReviewStatus.READY and self.session is not None

    @property
    def progress_fraction(self) -> float:
        if self.total_moves == 0:
            return 1.0
        return min(1.0, self.assessed / self.total_moves)

    def start(self, conn: sqlite3.Connection, engine: Analyser) -> "ReviewJob":
        """Begin analysing in a daemon thread. Returns immediately."""

        def on_progress(assessed: int, total: int) -> None:
            # Also the cancellation checkpoint: called once per analysed move.
            if self._cancelled:
                raise ReviewCancelled
            with self._lock:
                self.assessed = assessed
                self.total_moves = total

        def run() -> None:
            try:
                plan = build_review(
                    conn,
                    engine,
                    self.parsed,
                    game_id=self.game.id,
                    my_colour=self.my_colour,
                    depth=self.depth,
                    on_progress=on_progress,
                )
            except ReviewCancelled:
                with self._lock:
                    self.status = ReviewStatus.CANCELLED
                return
            except Exception as exc:  # surfaced to the UI via `error`
                with self._lock:
                    self.status = ReviewStatus.FAILED
                    self.error = f"{type(exc).__name__}: {exc}"
                return
            with self._lock:
                self.session = ReviewSession(plan=plan)
                self.status = ReviewStatus.READY

        thread = threading.Thread(
            target=run, name=f"review-{self.game.id[:8]}", daemon=True
        )
        self._thread = thread
        thread.start()
        return self

    def cancel(self) -> None:
        """Ask the worker to stop at its next checkpoint.

        Must be followed by :meth:`wait` before anything the worker touches (in
        particular the database connection) is torn down.
        """
        self._cancelled = True

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the analysis finishes. Returns False if it is still going."""
        if self._thread is None:
            return self.status is not ReviewStatus.ANALYSING
        self._thread.join(timeout)
        return not self._thread.is_alive()


def create_job(
    game: StoredGame, parsed: ParsedGame, *, my_colour: str, depth: int
) -> ReviewJob:
    """Build a job for a game, counting my moves so progress has a denominator."""
    return ReviewJob(
        game=game,
        parsed=parsed,
        my_colour=my_colour,
        depth=depth,
        total_moves=count_my_moves(parsed, my_colour),
    )
