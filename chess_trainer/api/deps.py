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
from chess_trainer.explorer.lichess_client import LichessExplorerClient
from chess_trainer.db.connection import TrainerConnection, connect
from chess_trainer.engine.stockfish import EngineNotAvailable, StockfishEngine
from chess_trainer.session.flow import SessionFlow
from chess_trainer.srs.scheduler import CardQueue
from chess_trainer.inaccuracies.deck import InaccuracyDeck
from chess_trainer.api.scan_job import ScanJob

T = TypeVar("T")


class AppState:
    """Container for process-wide state, attached to ``app.state.ctx``."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.connection = connect(config.db_path)
        self.engine = StockfishEngine(config.stockfish_path)
        self.flow = SessionFlow()
        #: The opening-card queue for this session (requeues, grading state).
        self.card_queue = CardQueue()
        #: The card currently on screen, and how it is going.
        self.current_card_id: int | None = None
        self.card_attempts: list[str] = []
        self.card_shown: bool = False
        self.card_finished: bool = False
        #: The puzzle ("inaccuracy") deck for this session, and the card on screen.
        self.inaccuracy_deck = InaccuracyDeck()
        self.current_inaccuracy_id: int | None = None
        self.inaccuracy_attempts: list[str] = []
        #: Plies of the card's puzzle line played so far, and wrong tries in it.
        self.inaccuracy_progress: int = 0
        self.inaccuracy_wrong: int = 0
        self.inaccuracy_hinted: bool = False
        self.inaccuracy_shown: bool = False
        self.inaccuracy_finished: bool = False
        #: The game being scanned for puzzles, if any (the latest one stays
        #: until the next starts, so the page can show its outcome).
        self.scan_job: ScanJob | None = None
        self._explorer: LichessExplorerClient | None = None

    @property
    def conn(self) -> TrainerConnection:
        """The shared connection; safe to use from any thread."""
        return self.connection

    @property
    def explorer(self) -> LichessExplorerClient:
        """A lazily created Lichess explorer client, reused across requests."""
        if self._explorer is None:
            self._explorer = LichessExplorerClient(
                self.config.lichess_token, self.config.user_agent
            )
        return self._explorer

    def reset_card(self) -> None:
        """Forget the card on screen (served a new one, or left the step)."""
        self.current_card_id = None
        self.card_attempts = []
        self.card_shown = False
        self.card_finished = False

    def reset_inaccuracy(self) -> None:
        """Forget the inaccuracy card on screen."""
        self.current_inaccuracy_id = None
        self.inaccuracy_attempts = []
        self.inaccuracy_progress = 0
        self.inaccuracy_wrong = 0
        self.inaccuracy_hinted = False
        self.inaccuracy_shown = False
        self.inaccuracy_finished = False

    def shutdown(self) -> None:
        """Stop any scan, the engine and the explorer client, then the database."""
        if self.scan_job is not None:
            self.scan_job.cancel()
        self.engine.close()
        if self._explorer is not None:
            self._explorer.close()
            self._explorer = None
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


def require_explorer(state: State) -> LichessExplorerClient:
    """The explorer client; 503 with instructions when no token is set."""
    from chess_trainer.explorer.lichess_client import TOKEN_HELP

    client = state.explorer
    if not client.has_token:
        raise HTTPException(
            status_code=503,
            detail="The opening cards need a Lichess API token. " + TOKEN_HELP,
        )
    return client


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Explorer = Annotated[LichessExplorerClient, Depends(require_explorer)]
Cfg = Annotated[Config, Depends(get_config)]
Flow = Annotated[SessionFlow, Depends(get_flow)]
Engine = Annotated[StockfishEngine, Depends(require_engine)]
