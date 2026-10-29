"""Shared application state and FastAPI dependencies.

Everything with a lifetime longer than a request lives here: the config, the
the shared database connection, the Stockfish process and the session state.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, Request

from chess_trainer.config import Config
from chess_trainer.db.connection import TrainerConnection, connect
from chess_trainer.engine.stockfish import EngineNotAvailable, StockfishEngine
from chess_trainer.session.flow import SessionFlow

T = TypeVar("T")


class AppState:
    """Container for process-wide state, attached to ``app.state.ctx``."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.connection = connect(config.db_path)
        self.engine = StockfishEngine(config.stockfish_path)
        self.flow = SessionFlow()

    @property
    def conn(self) -> TrainerConnection:
        """The shared connection; safe to use from any thread."""
        return self.connection

    def shutdown(self) -> None:
        self.engine.close()
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


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Cfg = Annotated[Config, Depends(get_config)]
Flow = Annotated[SessionFlow, Depends(get_flow)]
Engine = Annotated[StockfishEngine, Depends(require_engine)]
