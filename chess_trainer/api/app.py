"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chess_trainer import __version__, paths
from chess_trainer.api.deps import AppState
from chess_trainer.api.routers import board, engine, health, session, streak
from chess_trainer.config import Config, load_config
from chess_trainer.db import schema

ROUTERS = (
    health.router,
    session.router,
    streak.router,
    engine.router,
    board.router,
)


def create_app(config: Config | None = None) -> FastAPI:
    """Build the app. Pass a ``Config`` to override the environment (tests)."""
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = AppState(cfg)
        app.state.ctx = state
        schema.migrate(state.conn)
        try:
            yield
        finally:
            state.shutdown()

    app = FastAPI(
        title="chess-trainer",
        version=__version__,
        summary="Local daily chess review and opening drills",
        lifespan=lifespan,
    )

    for router in ROUTERS:
        app.include_router(router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the vendored frontend from the repo, with no external requests."""
    try:
        frontend = paths.find_frontend_dir()
    except FileNotFoundError:  # pragma: no cover - only in odd installs
        return

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html")

    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
