"""Health and configuration introspection."""

from __future__ import annotations

from fastapi import APIRouter

from chess_trainer import __version__
from chess_trainer.api.deps import Cfg, State
from chess_trainer.api.schemas import HealthOut

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(state: State, config: Cfg) -> HealthOut:
    return HealthOut(
        version=__version__,
        engine=state.engine_status(),
        database=str(config.db_path),
        chesscom_username=config.chesscom_username,
        lichess_token_present=config.lichess_token is not None,
        timezone=config.timezone,
    )
