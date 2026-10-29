"""Request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from chess_trainer.engine.eval_format import bar_fraction, format_eval
from chess_trainer.engine.eval_types import Eval
from chess_trainer.session.flow import SessionFlow
from chess_trainer.session.steps import Step
from chess_trainer.streak.streak import Streak

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# -- evaluation ----------------------------------------------------------
class EvalOut(BaseModel):
    """An evaluation, ready for the eval bar. Always White's perspective."""

    cp: int | None = None
    mate: int | None = None
    text: str
    fraction: float = Field(description="Share of the bar filled by White, 0..1")

    @classmethod
    def of(cls, evaluation: Eval) -> "EvalOut":
        return cls(
            cp=evaluation.cp,
            mate=evaluation.mate,
            text=format_eval(evaluation),
            fraction=bar_fraction(evaluation),
        )


class EvalRequest(BaseModel):
    fen: str = Field(default=START_FEN, description="Position to evaluate")
    depth: int | None = Field(default=None, ge=1, le=40)


class EvalResponse(BaseModel):
    fen: str
    depth: int
    evaluation: EvalOut
    best_move: str | None = None
    cached: bool = False


# -- session -------------------------------------------------------------
class StepOut(BaseModel):
    step: Step
    position: int
    title: str
    enabled: bool
    completed: bool
    current: bool


class SessionOut(BaseModel):
    started: bool
    current: Step | None
    finished: bool
    steps: list[StepOut]

    @classmethod
    def of(cls, flow: SessionFlow) -> "SessionOut":
        return cls(
            started=flow.started,
            current=flow.current,
            finished=flow.is_finished,
            steps=[
                StepOut(
                    step=i.step,
                    position=i.position,
                    title=i.title,
                    enabled=i.enabled,
                    completed=i.completed,
                    current=i.current,
                )
                for i in flow.step_bar()
            ],
        )


class StartSessionRequest(BaseModel):
    steps: list[Step] | None = Field(
        default=None,
        description="Steps to run; omit or send null for all four.",
    )


# -- streak --------------------------------------------------------------
class StreakOut(BaseModel):
    current: int
    longest: int
    active_today: bool
    total_days: int

    @classmethod
    def of(cls, streak: Streak) -> "StreakOut":
        return cls(
            current=streak.current,
            longest=streak.longest,
            active_today=streak.active_today,
            total_days=streak.total_days,
        )


class SessionAndStreakOut(BaseModel):
    """Returned when completing a step, which can move the streak."""

    session: SessionOut
    streak: StreakOut


# -- health --------------------------------------------------------------
class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    engine: dict[str, object]
    database: str
    chesscom_username: str
    lichess_token_present: bool
    timezone: str
