"""Position evaluation, which drives the eval bar."""

from __future__ import annotations

import chess
from fastapi import APIRouter, HTTPException

from chess_trainer.api.deps import Cfg, Conn, Engine, State
from chess_trainer.api.schemas import EvalOut, EvalRequest, EvalResponse
from chess_trainer.engine import analysis

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _validate_fen(fen: str) -> str:
    try:
        chess.Board(fen)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid FEN: {exc}") from exc
    return fen


@router.post("/eval", response_model=EvalResponse)
async def evaluate(
    payload: EvalRequest,
    state: State,
    conn: Conn,
    engine: Engine,
    config: Cfg,
) -> EvalResponse:
    """Evaluate a position at the configured depth, reading through the cache.

    The frontend calls this after every move, including wrong retries, so the
    eval bar always shows what the last attempt cost.
    """
    fen = _validate_fen(payload.fen)
    depth = payload.depth or config.engine_depth

    # The cache lookup and the search happen together in one worker thread, so
    # a slow search never blocks the event loop and the fast path stays cheap.
    def run() -> tuple[object, bool]:
        cached = analysis.cached_only(conn, fen, depth)
        if cached is not None:
            return cached, True
        return analysis.analyse(conn, engine, fen, depth), False

    result, was_cached = await state.in_thread(run)
    return EvalResponse(
        fen=fen,
        depth=depth,
        evaluation=EvalOut.of(result.evaluation),
        best_move=result.best_move,
        cached=was_cached,
    )
