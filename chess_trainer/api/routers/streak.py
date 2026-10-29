"""Current and longest streak."""

from __future__ import annotations

from fastapi import APIRouter

from chess_trainer.api.deps import Cfg, Conn
from chess_trainer.api.schemas import StreakOut
from chess_trainer.streak import tracker

router = APIRouter(prefix="/api/streak", tags=["streak"])


@router.get("", response_model=StreakOut)
def get_streak(conn: Conn, config: Cfg) -> StreakOut:
    return StreakOut.of(tracker.get_streak(conn, tz_name=config.timezone))
