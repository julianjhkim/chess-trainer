"""The names I play under: read and replace the list.

They decide which side I had in a pasted game when a revision card is made.
"""

from __future__ import annotations

from fastapi import APIRouter

from chess_trainer.api.deps import Cfg, Conn
from chess_trainer.api.schemas import MeOut, MeRequest
from chess_trainer.db import usernames_repo

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=MeOut)
def get_me(conn: Conn, config: Cfg) -> MeOut:
    return MeOut(usernames=usernames_repo.get(conn, seed=config.chesscom_username or None))


@router.put("", response_model=MeOut)
def put_me(payload: MeRequest, conn: Conn) -> MeOut:
    return MeOut(usernames=usernames_repo.put(conn, payload.usernames))
