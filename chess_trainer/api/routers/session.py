"""Session lifecycle: start, navigate between steps, complete a step."""

from __future__ import annotations

from fastapi import APIRouter

from chess_trainer.api.deps import Cfg, Conn, Flow
from chess_trainer.api.schemas import (
    SessionAndStreakOut,
    SessionOut,
    StartSessionRequest,
    StreakOut,
)
from chess_trainer.session.steps import Step
from chess_trainer.streak import tracker

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("", response_model=SessionOut)
def get_session(flow: Flow) -> SessionOut:
    return SessionOut.of(flow)


@router.post("/start", response_model=SessionOut)
def start_session(payload: StartSessionRequest, flow: Flow) -> SessionOut:
    """Begin a session with the selected steps (all four when none are given),
    at ``start_at`` if given, else the first of them."""
    flow.start(set(payload.steps) if payload.steps else None, at=payload.start_at)
    return SessionOut.of(flow)


@router.post("/reset", response_model=SessionOut)
def reset_session(flow: Flow) -> SessionOut:
    flow.reset()
    return SessionOut.of(flow)


@router.post("/jump/{step}", response_model=SessionOut)
def jump(step: Step, flow: Flow) -> SessionOut:
    """Jump to any step, forwards or backwards, from the step bar."""
    flow.jump_to(step)
    return SessionOut.of(flow)


@router.post("/complete/{step}", response_model=SessionAndStreakOut)
def complete(step: Step, flow: Flow, conn: Conn, config: Cfg) -> SessionAndStreakOut:
    """Mark a step finished, advance, and count the day towards the streak."""
    flow.complete(step)
    streak = tracker.record_step(conn, tz_name=config.timezone)
    return SessionAndStreakOut(
        session=SessionOut.of(flow), streak=StreakOut.of(streak)
    )
