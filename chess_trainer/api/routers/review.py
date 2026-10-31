"""Running a game review: start the analysis, try moves, reveal the answer."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from chess_trainer import rules
from chess_trainer.api.deps import Cfg, Conn, Engine, State
from chess_trainer.api.schemas import (
    AcknowledgeResponse,
    AttemptRequest,
    AttemptResponse,
    EvalOut,
    ExplanationResponse,
    HintOut,
    HintResponse,
    ReviewStateOut,
    SessionOut,
    ShowAnswerRequest,
    ShowAnswerResponse,
    StartReviewRequest,
    StreakOut,
)
from chess_trainer.config import Config
from chess_trainer.db import game_reviews_repo, games_repo
from chess_trainer.engine import analysis
from chess_trainer.pgn import parse
from chess_trainer.pgn.parse import PgnParseError
from chess_trainer.inaccuracies import deck
from chess_trainer.inaccuracies.card_from_review import card_from_review
from chess_trainer.review import explain as explain_module, review_job
from chess_trainer.review.review_job import ReviewJob
from chess_trainer.session.steps import Step
from chess_trainer.streak import seoul_day, tracker

router = APIRouter(prefix="/api/review", tags=["review"])

#: Only this step runs a game review.
REVIEW_STEPS = (Step.REVIEW_NEW_GAME,)


def _require_review_step(step: Step) -> Step:
    if step not in REVIEW_STEPS:
        raise HTTPException(
            status_code=422,
            detail=f"{step.value} is not a review step; expected one of "
            + ", ".join(s.value for s in REVIEW_STEPS),
        )
    return step


def _require_job(state: State, step: Step) -> ReviewJob:
    job = state.reviews.get(step)
    if job is None:
        raise HTTPException(
            status_code=409,
            detail=f"No review is running for {step.value}. Start one first.",
        )
    return job


def _require_ready(job: ReviewJob, step: Step) -> ReviewJob:
    if job.status is review_job.ReviewStatus.FAILED:
        raise HTTPException(status_code=500, detail=job.error or "Review failed.")
    if not job.is_ready:
        raise HTTPException(
            status_code=409,
            detail=f"The review for {step.value} is still analysing "
            f"({job.assessed}/{job.total_moves} moves).",
        )
    return job


@router.post("/start", response_model=ReviewStateOut)
def start(
    payload: StartReviewRequest,
    state: State,
    conn: Conn,
    engine: Engine,
    config: Cfg,
) -> ReviewStateOut:
    """Begin reviewing a game, analysing in the background.

    Returns immediately with ``status: analysing``; poll ``GET /api/review/{step}``
    for progress. A review already in progress or finished for this step is
    returned as-is unless ``restart`` is set.
    """
    step = _require_review_step(payload.step)

    game = (
        games_repo.get(conn, payload.game_id)
        if payload.game_id
        else games_repo.latest(conn)
    )
    if game is None:
        raise HTTPException(
            status_code=404,
            detail="No game to review yet. Fetch one from chess.com or paste a PGN.",
        )

    existing = state.reviews.get(step)
    if (
        existing is not None
        and not payload.restart
        and existing.game.id == game.id
        and existing.status is not review_job.ReviewStatus.FAILED
    ):
        return ReviewStateOut.of(step, existing)

    try:
        parsed = parse.parse_pgn(game.pgn)
    except PgnParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        job = review_job.create_job(
            game, parsed, my_colour=game.my_color, depth=config.engine_depth
        )
    except ValueError as exc:
        # parse_pgn already rejects illegal lines, so this is belt and braces.
        raise HTTPException(
            status_code=422, detail=f"This game cannot be replayed: {exc}"
        ) from exc
    state.reviews[step] = job
    job.start(conn, engine)
    return ReviewStateOut.of(step, job)


@router.get("/{step}", response_model=ReviewStateOut)
def get_state(step: Step, state: State) -> ReviewStateOut:
    """Progress and current state of a review; polled while it analyses."""
    _require_review_step(step)
    return ReviewStateOut.of(step, _require_job(state, step))


@router.post("/attempt", response_model=AttemptResponse)
async def attempt(
    payload: AttemptRequest,
    state: State,
    conn: Conn,
    engine: Engine,
    config: Cfg,
) -> AttemptResponse:
    """Try a move. Correct only if it is the engine's top-1 at the same depth.

    Wrong answers are unlimited; every attempt is evaluated so the eval bar can
    show what that attempt would have cost.
    """
    step = _require_review_step(payload.step)
    job = _require_ready(_require_job(state, step), step)
    session = job.session
    assert session is not None  # _require_ready checked
    target = session.target
    if target is None:
        raise HTTPException(
            status_code=409, detail="This game had no inaccuracy to solve."
        )
    if session.finished:
        raise HTTPException(status_code=409, detail="This review is already finished.")

    try:
        uci = rules.resolve_uci(
            target.fen_before, payload.from_square, payload.to_square, payload.promotion
        )
        move = rules.apply_move(target.fen_before, uci)
    except rules.IllegalMove as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    correct = session.attempt(uci)
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)

    response = AttemptResponse(
        correct=correct,
        uci=uci,
        san=move.san,
        evaluation=EvalOut.of(evaluation),
        fen_after=move.fen_after,
        attempts=session.attempt_count,
        review=ReviewStateOut.of(step, job),
    )
    if correct:
        _finish(state, conn, config, step, job, response)
    return response


@router.post("/hint", response_model=HintResponse)
def hint(payload: ShowAnswerRequest, state: State) -> HintResponse:
    """Say which piece the answer moves -- its square, not where it goes.

    Only while the position is still being solved; the review history notes
    that a hint was taken.
    """
    step = _require_review_step(payload.step)
    job = _require_ready(_require_job(state, step), step)
    session = job.session
    assert session is not None
    target = session.target
    if target is None:
        raise HTTPException(
            status_code=409, detail="This game had no inaccuracy to solve."
        )
    if session.finished:
        raise HTTPException(status_code=409, detail="This review is already finished.")

    square = session.hint()
    return HintResponse(
        hint=HintOut.of(target.fen_before, square),
        review=ReviewStateOut.of(step, job),
    )


@router.post("/explain", response_model=ExplanationResponse)
async def explain(
    payload: ShowAnswerRequest,
    state: State,
    conn: Conn,
    engine: Engine,
    config: Cfg,
) -> ExplanationResponse:
    """Why the engine's move is the answer: its line, and the line after mine.

    Only once the review is over, since it names the answer. Reads the engine's
    lines through the cache; a position cached before lines were kept is
    searched once more.
    """
    step = _require_review_step(payload.step)
    job = _require_ready(_require_job(state, step), step)
    session = job.session
    assert session is not None
    target = session.target
    if target is None:
        raise HTTPException(
            status_code=409, detail="This game had no inaccuracy to explain."
        )
    if not session.finished:
        raise HTTPException(
            status_code=409, detail="Solve the position or show the answer first."
        )

    after_best = rules.apply_move(target.fen_before, target.best_move_uci).fen_after
    after_mine = rules.apply_move(target.fen_before, target.my_move_uci).fen_after

    def run():
        best = analysis.analyse(conn, engine, after_best, config.engine_depth, need_line=True)
        mine = analysis.analyse(conn, engine, after_mine, config.engine_depth, need_line=True)
        return best, mine

    best, mine = await state.in_thread(run)
    return ExplanationResponse.of(
        explain_module.explain(
            target.fen_before,
            best_uci=target.best_move_uci,
            best_reply_pv=best.pv,
            best_eval=best.evaluation,
            my_uci=target.my_move_uci,
            my_reply_pv=mine.pv,
            eval_before=target.eval_before,
            eval_after=target.eval_after,
            win_percent_drop=target.win_percent_drop,
        )
    )


@router.post("/show-answer", response_model=ShowAnswerResponse)
async def show_answer(
    payload: ShowAnswerRequest,
    state: State,
    conn: Conn,
    engine: Engine,
    config: Cfg,
) -> ShowAnswerResponse:
    """Reveal the engine's move, which ends the review."""
    step = _require_review_step(payload.step)
    job = _require_ready(_require_job(state, step), step)
    session = job.session
    assert session is not None
    target = session.target
    if target is None:
        raise HTTPException(
            status_code=409, detail="This game had no inaccuracy to solve."
        )

    best_uci = session.show_answer()
    move = rules.apply_move(target.fen_before, best_uci)
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)

    response = ShowAnswerResponse(
        best_move_uci=best_uci,
        best_move_san=move.san,
        fen_after=move.fen_after,
        evaluation=EvalOut.of(evaluation),
        review=ReviewStateOut.of(step, job),
    )
    _finish(state, conn, config, step, job, response)
    return response


@router.post("/acknowledge", response_model=AcknowledgeResponse)
def acknowledge(
    payload: ShowAnswerRequest, state: State, conn: Conn, config: Cfg
) -> AcknowledgeResponse:
    """Close a review that needs no solving, i.e. a game with no inaccuracy.

    The step still counts: it was completed, so it counts towards the streak and
    is written to the review history (with the move columns left empty).
    """
    step = _require_review_step(payload.step)
    job = _require_ready(_require_job(state, step), step)
    session = job.session
    assert session is not None
    if session.target is not None and not session.finished:
        raise HTTPException(
            status_code=409,
            detail="This review has a position to solve; play the move or show the answer.",
        )

    response = AcknowledgeResponse(review=ReviewStateOut.of(step, job))
    _finish(state, conn, config, step, job, response)
    return response


async def _evaluate(state: State, conn: Conn, engine: Engine, fen: str, config: Config):
    """Evaluate a position for the eval bar, off the event loop."""

    def run():
        return analysis.analyse(conn, engine, fen, config.engine_depth).evaluation

    return await state.in_thread(run)


def _finish(
    state: State,
    conn: sqlite3.Connection,
    config: Config,
    step: Step,
    job: ReviewJob,
    response: AttemptResponse | ShowAnswerResponse | AcknowledgeResponse,
) -> None:
    """End a review: write the history row, complete the step, move the streak.

    Guarded by ``session.recorded`` so solving and then revealing -- or a
    duplicate request -- cannot write the history twice.
    """
    session = job.session
    assert session is not None
    if session.recorded:
        response.review = ReviewStateOut.of(step, job)
        return

    session.recorded = True
    today = seoul_day.today(tz_name=config.timezone)
    game_reviews_repo.record(conn, session.to_history(today))

    # The slip becomes an inaccuracy card, first due tomorrow.
    if session.target is not None:
        added = deck.add_card(
            conn,
            card_from_review(
                session.target,
                game_id=job.game.id,
                my_colour=job.my_colour,
                depth=job.depth,
            ),
            today=today,
        )
        session.card_due_on = added.due_on
        session.card_created = added.created

    state.flow.complete(step)
    streak = tracker.record_step(conn, tz_name=config.timezone)

    response.review = ReviewStateOut.of(step, job)
    response.session = SessionOut.of(state.flow)
    response.streak = StreakOut.of(streak)
