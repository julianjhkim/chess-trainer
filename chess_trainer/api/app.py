"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chess_trainer import __version__, paths
from chess_trainer.api.deps import AppState
from chess_trainer.api.routers import (
    board,
    cards,
    engine,
    health,
    inaccuracy_cards,
    me,
    session,
    streak,
)
from chess_trainer.config import Config, load_config
from chess_trainer.db import schema
from chess_trainer.openings import prune

ROUTERS = (
    health.router,
    session.router,
    streak.router,
    engine.router,
    board.router,
    cards.router,
    inaccuracy_cards.router,
    me.router,
)


def create_app(config: Config | None = None) -> FastAPI:
    """Build the app. Pass a ``Config`` to override the environment (tests)."""
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = AppState(cfg)
        app.state.ctx = state
        schema.migrate(state.conn)
        prune.prune_black_only(state.conn)
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


#: Every frontend file is revalidated on each load (a cheap 304 on localhost),
#: so an updated app is never run from stale cached modules.
NO_CACHE = {"Cache-Control": "no-cache"}


class _RevalidatedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


def _mount_frontend(app: FastAPI) -> None:
    """Serve the vendored frontend from the repo, with no external requests."""
    try:
        frontend = paths.find_frontend_dir()
    except FileNotFoundError:  # pragma: no cover - only in odd installs
        return

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html", headers=NO_CACHE)

    app.mount("/", _RevalidatedStaticFiles(directory=frontend, html=True), name="frontend")
