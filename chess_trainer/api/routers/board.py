"""Board rules: legal moves and move application.

The frontend has no rules engine of its own; it asks here. That keeps a single
source of truth for legality and means a drill answer cannot be judged
client-side.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chess_trainer import rules

router = APIRouter(prefix="/api/board", tags=["board"])


class FenRequest(BaseModel):
    fen: str = Field(default=rules.START_FEN)


class PositionStateOut(BaseModel):
    fen: str
    turn: str
    dests: dict[str, list[str]]
    in_check: bool
    game_over: bool
    outcome: str | None = None


class MoveRequest(BaseModel):
    fen: str
    from_square: str = Field(alias="from", min_length=2, max_length=2)
    to_square: str = Field(alias="to", min_length=2, max_length=2)
    promotion: str | None = None

    model_config = {"populate_by_name": True}


class MoveOut(BaseModel):
    fen: str
    uci: str
    san: str
    promotion: str | None = None
    is_capture: bool
    game_over: bool
    outcome: str | None = None
    state: PositionStateOut


def _state_out(fen: str) -> PositionStateOut:
    state = rules.position_state(fen)
    return PositionStateOut(
        fen=state.fen,
        turn=state.turn,
        dests=state.dests,
        in_check=state.in_check,
        game_over=state.game_over,
        outcome=state.outcome,
    )


@router.post("/state", response_model=PositionStateOut)
def state(payload: FenRequest) -> PositionStateOut:
    """Legal destinations and status for a position."""
    try:
        return _state_out(payload.fen)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid FEN: {exc}") from exc


@router.post("/move", response_model=MoveOut)
def move(payload: MoveRequest) -> MoveOut:
    """Apply a move and report the SAN plus the new position."""
    try:
        uci = rules.resolve_uci(
            payload.fen, payload.from_square, payload.to_square, payload.promotion
        )
        result = rules.apply_move(payload.fen, uci)
    except rules.IllegalMove as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid position: {exc}") from exc

    return MoveOut(
        fen=result.fen_after,
        uci=result.uci,
        san=result.san,
        promotion=result.promotion,
        is_capture=result.is_capture,
        game_over=result.game_over,
        outcome=result.outcome,
        state=_state_out(result.fen_after),
    )
