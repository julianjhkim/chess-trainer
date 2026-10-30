"""Request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from chess_trainer.db.games_repo import StoredGame
from chess_trainer.engine.eval_format import bar_fraction, format_eval
from chess_trainer.engine.eval_types import Eval
from chess_trainer.review.review_job import ReviewJob, ReviewStatus
from chess_trainer.review.review_session import ReviewTarget
from chess_trainer.review.verdict import ReviewSummary
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


# -- games ---------------------------------------------------------------
class GameOut(BaseModel):
    """A stored game, as the UI needs to describe it."""

    id: str
    url: str | None = None
    my_colour: str
    opponent: str | None = None
    white_username: str | None = None
    black_username: str | None = None
    my_result: str | None = None
    time_class: str | None = None
    end_time: int | None = None
    source: str
    move_count: int | None = None

    @classmethod
    def of(cls, game: StoredGame, *, move_count: int | None = None) -> "GameOut":
        return cls(
            id=game.id,
            url=game.url,
            my_colour=game.my_color,
            opponent=game.opponent,
            white_username=game.white_username,
            black_username=game.black_username,
            my_result=game.my_result,
            time_class=game.time_class,
            end_time=game.end_time,
            source=game.source,
            move_count=move_count,
        )


class GameResponse(BaseModel):
    game: GameOut


class LatestGameResponse(BaseModel):
    game: GameOut | None = None


class PastePgnRequest(BaseModel):
    pgn: str = Field(min_length=1, description="Full PGN text of the game")


class PollRequest(BaseModel):
    budget_seconds: float | None = Field(
        default=None,
        gt=0,
        le=30,
        description="How long this polling window may take (default ~12s).",
    )


class PollResponse(BaseModel):
    """One polling window. The client repeats these until the ~2 minute budget."""

    found: bool
    game: GameOut | None = None
    attempts: int
    waited: float
    error: str | None = None
    total_budget_seconds: float


# -- review --------------------------------------------------------------
class ReviewTargetOut(BaseModel):
    """The position to solve. The answer itself is deliberately not included."""

    ply: int
    move_number: int
    move_label: str
    fen_before: str
    replay_ucis: list[str]
    mover_is_white: bool
    orientation: str


class ReviewSummaryOut(BaseModel):
    found_an_inaccuracy: bool
    move_label: str | None = None
    my_move_san: str | None = None
    my_move_uci: str | None = None
    classification: str | None = None
    best_move_san: str | None = None
    best_move_uci: str | None = None
    eval_before: EvalOut | None = None
    eval_after: EvalOut | None = None
    win_percent_drop: float | None = None
    attempts: int = 0
    used_show_answer: bool = False
    solved_first_try: bool = False

    @classmethod
    def of(cls, summary: ReviewSummary) -> "ReviewSummaryOut":
        return cls(
            found_an_inaccuracy=summary.found_an_inaccuracy,
            move_label=summary.move_label,
            my_move_san=summary.my_move_san,
            my_move_uci=summary.my_move_uci,
            classification=summary.classification,
            best_move_san=summary.best_move_san,
            best_move_uci=summary.best_move_uci,
            eval_before=EvalOut.of(summary.eval_before) if summary.eval_before else None,
            eval_after=EvalOut.of(summary.eval_after) if summary.eval_after else None,
            win_percent_drop=summary.win_percent_drop,
            attempts=summary.attempts,
            used_show_answer=summary.used_show_answer,
            solved_first_try=summary.solved_first_try,
        )


class ReviewStateOut(BaseModel):
    """Everything the review view needs, at any point in its lifecycle."""

    step: Step
    status: ReviewStatus
    game: GameOut
    orientation: str
    depth: int
    assessed: int
    total_moves: int
    progress: float
    error: str | None = None
    #: Present once the analysis is done and an inaccuracy was found.
    target: ReviewTargetOut | None = None
    #: True when the game held no inaccuracy at all.
    no_inaccuracy: bool = False
    attempts: int = 0
    used_show_answer: bool = False
    solved: bool = False
    finished: bool = False
    summary: ReviewSummaryOut | None = None

    @classmethod
    def of(cls, step: Step, job: ReviewJob) -> "ReviewStateOut":
        orientation = job.my_colour
        state = cls(
            step=step,
            status=job.status,
            game=GameOut.of(job.game, move_count=job.parsed.move_count),
            orientation=orientation,
            depth=job.depth,
            assessed=job.assessed,
            total_moves=job.total_moves,
            progress=job.progress_fraction,
            error=job.error,
        )
        session = job.session
        if session is None:
            return state

        target = session.target
        state.attempts = session.attempt_count
        state.used_show_answer = session.used_show_answer
        state.solved = session.solved
        state.finished = session.finished
        state.no_inaccuracy = target is None
        if target is not None and not session.finished:
            state.target = _target_out(target, orientation)
        if session.finished:
            state.summary = ReviewSummaryOut.of(session.summary())
            if target is not None:
                state.target = _target_out(target, orientation)
        return state


def _target_out(target: ReviewTarget, orientation: str) -> ReviewTargetOut:
    return ReviewTargetOut(
        ply=target.ply,
        move_number=target.move_number,
        move_label=target.move_label,
        fen_before=target.fen_before,
        replay_ucis=list(target.replay_ucis),
        mover_is_white=target.mover_is_white,
        orientation=orientation,
    )


class StartReviewRequest(BaseModel):
    step: Step
    #: Omit to review the most recent stored game.
    game_id: str | None = None
    #: Re-analyse from scratch rather than resuming an in-progress review.
    restart: bool = False


class AttemptRequest(BaseModel):
    step: Step
    from_square: str = Field(alias="from", min_length=2, max_length=2)
    to_square: str = Field(alias="to", min_length=2, max_length=2)
    promotion: str | None = None

    model_config = {"populate_by_name": True}


class AttemptResponse(BaseModel):
    correct: bool
    uci: str
    san: str
    #: Evaluation of the position after the attempted move, for the eval bar.
    evaluation: EvalOut
    fen_after: str
    attempts: int
    review: ReviewStateOut
    session: SessionOut | None = None
    streak: StreakOut | None = None


class AcknowledgeResponse(BaseModel):
    """Returned when closing a review that had nothing to solve."""

    review: ReviewStateOut
    session: SessionOut | None = None
    streak: StreakOut | None = None


class ShowAnswerRequest(BaseModel):
    step: Step


class ShowAnswerResponse(BaseModel):
    best_move_uci: str
    best_move_san: str
    fen_after: str
    evaluation: EvalOut
    review: ReviewStateOut
    session: SessionOut | None = None
    streak: StreakOut | None = None
