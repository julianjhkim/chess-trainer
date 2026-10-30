"""Shared application state and FastAPI dependencies.

Everything with a lifetime longer than a request lives here: the config, the
the shared database connection, the Stockfish process and the session state.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, Request

from chess_trainer.chesscom.client import ChessComClient
from chess_trainer.config import Config
from chess_trainer.db.connection import TrainerConnection, connect
from chess_trainer.engine.stockfish import EngineNotAvailable, StockfishEngine
from chess_trainer.review.review_job import ReviewJob
from chess_trainer.session.flow import SessionFlow
from chess_trainer.session.steps import Step

T = TypeVar("T")


class AppState:
    """Container for process-wide state, attached to ``app.state.ctx``."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.connection = connect(config.db_path)
        self.engine = StockfishEngine(config.stockfish_path)
        self.flow = SessionFlow()
        #: One review per review step, so stepping away and back keeps progress.
        self.reviews: dict[Step, ReviewJob] = {}
        self._chesscom: ChessComClient | None = None

    @property
    def conn(self) -> TrainerConnection:
        """The shared connection; safe to use from any thread."""
        return self.connection

    @property
    def chesscom(self) -> ChessComClient:
        """A lazily created chess.com client, reused across requests."""
        if self._chesscom is None:
            self._chesscom = ChessComClient(
                self.config.chesscom_username, self.config.user_agent
            )
        return self._chesscom

    #: How long shutdown waits for a review thread to notice it was cancelled.
    JOIN_TIMEOUT_SECONDS = 10.0

    def shutdown(self) -> None:
        """Tear down in an order that cannot pull the rug from a worker thread.

        A review runs in a background thread that reads and writes the SQLite
        connection. Closing that connection underneath it is a use-after-free
        and segfaults the interpreter, so the jobs are cancelled and joined
        first. Closing the engine before joining makes any in-flight search
        fail immediately, which is what lets a long analysis stop promptly.
        """
        jobs = list(self.reviews.values())
        for job in jobs:
            job.cancel()

        self.engine.close()

        stragglers = [job for job in jobs if not job.wait(self.JOIN_TIMEOUT_SECONDS)]

        if self._chesscom is not None:
            self._chesscom.close()
            self._chesscom = None

        if stragglers:
            # Leaking a connection on the way out is far better than crashing:
            # a thread is still holding it, and the process is exiting anyway.
            return
        self.connection.close()

    async def in_thread(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Run blocking work (engine + SQLite) off the event loop."""
        return await asyncio.to_thread(func, *args, **kwargs)

    def engine_status(self) -> dict[str, object]:
        """Whether the engine binary looks usable, without starting a search."""
        path = self.config.stockfish_path
        return {
            "path": str(path),
            "exists": path.exists(),
            "running": self.engine.is_running,
            "depth": self.config.engine_depth,
        }


def get_state(request: Request) -> AppState:
    return request.app.state.ctx  # type: ignore[no-any-return]


State = Annotated[AppState, Depends(get_state)]


def get_config(state: State) -> Config:
    return state.config


def get_conn(state: State) -> sqlite3.Connection:
    return state.conn


def get_flow(state: State) -> SessionFlow:
    return state.flow


def require_engine(state: State) -> StockfishEngine:
    """The engine, started if necessary; 503 with a readable message if absent."""
    try:
        state.engine.start()
    except EngineNotAvailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return state.engine


def get_chesscom(state: State) -> ChessComClient:
    return state.chesscom


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
ChessCom = Annotated[ChessComClient, Depends(get_chesscom)]
Cfg = Annotated[Config, Depends(get_config)]
Flow = Annotated[SessionFlow, Depends(get_flow)]
Engine = Annotated[StockfishEngine, Depends(require_engine)]
