"""Inaccuracy cards: drilling the first slip of each reviewed game again.

The answer is the engine's move recorded when the game was reviewed (the
same strict top-1 as the review). Grading and scheduling are the opening
cards' modified SM-2; a hint caps the grade at q=3.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from chess_trainer import rules
from chess_trainer.api.deps import Cfg, Conn, Engine, State
from chess_trainer.api.schemas import (
    CardAttemptRequest,
    EvalOut,
    HintOut,
    InaccuracyAttemptResponse,
    InaccuracyCardOut,
    InaccuracyCountsOut,
    InaccuracyGradeOut,
    InaccuracyResultOut,
    InaccuracyStateOut,
    SessionOut,
    StreakOut,
)
from chess_trainer.config import Config
from chess_trainer.db import games_repo, inaccuracy_cards_repo as repo
from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard
from chess_trainer.engine import analysis
from chess_trainer.inaccuracies.deck import DeckAnswer, DeckItem
from chess_trainer.session.steps import Step
from chess_trainer.srs.due import CardSource
from chess_trainer.streak import seoul_day, tracker

router = APIRouter(prefix="/api/inaccuracy-cards", tags=["inaccuracy-cards"])


def _today(config: Config):
    return seoul_day.today(tz_name=config.timezone)


def _counts(state: State, conn: sqlite3.Connection, config: Config) -> InaccuracyCountsOut:
    counts = state.inaccuracy_deck.counts(conn, _today(config))
    return InaccuracyCountsOut(
        due=counts.due,
        relearning=counts.relearning,
        total=counts.total,
        next_due_on=counts.next_due_on.isoformat() if counts.next_due_on else None,
    )


def _card_out(conn: sqlite3.Connection, card: InaccuracyCard, source: CardSource) -> InaccuracyCardOut:
    game = games_repo.get(conn, card.game_id) if card.game_id else None
    schedule = repo.get_schedule(conn, card.id or 0)
    return InaccuracyCardOut(
        id=card.id or 0,
        fen=card.fen,
        orientation=card.my_colour,
        last_move_uci=card.last_move_uci,
        move_number=card.move_number,
        classification=card.classification,
        my_move_uci=card.my_move_uci,
        my_move_san=card.my_move_san,
        move_label=card.move_label,
        source=source.value,
        opponent=game.opponent if game else None,
        played_on=game.end_time if game else None,
        interval_days=schedule.interval_days if schedule else None,
        reps=schedule.reps if schedule else 0,
    )


def _hint_out(card: InaccuracyCard) -> HintOut:
    return HintOut.of(card.fen, card.best_move_uci[:2])


def _current(state: State, conn: sqlite3.Connection) -> InaccuracyCard:
    if state.current_inaccuracy_id is None:
        raise HTTPException(
            status_code=409, detail="No card is on screen. Ask for the next one first."
        )
    card = repo.get(conn, state.current_inaccuracy_id)
    if card is None:  # pragma: no cover - deleted under us
        state.reset_inaccuracy()
        raise HTTPException(status_code=409, detail="That card no longer exists.")
    return card


def _require_open(state: State) -> None:
    if state.inaccuracy_finished:
        raise HTTPException(
            status_code=409, detail="This card is finished. Ask for the next one."
        )


def _result_out(card: InaccuracyCard, answer: DeckAnswer, *, revealed: bool) -> InaccuracyResultOut:
    result = answer.result
    return InaccuracyResultOut(
        answer_uci=card.best_move_uci,
        answer_san=card.best_move_san,
        my_move_uci=card.my_move_uci,
        my_move_san=card.my_move_san,
        move_label=card.move_label,
        classification=card.classification,
        win_percent_drop=card.win_percent_drop,
        revealed=revealed,
        grade=InaccuracyGradeOut(
            quality=answer.quality,
            description=answer.description,
            passed=answer.passed,
            requeued=answer.requeued,
            interval_days=result.interval_days if result else None,
            due_on=result.due_on.isoformat() if result else None,
            ef=result.state.ef if result else None,
        ),
    )


@router.get("/state", response_model=InaccuracyStateOut)
def get_state(state: State, conn: Conn, config: Cfg) -> InaccuracyStateOut:
    """The card on screen, if any, and what is waiting."""
    counts = _counts(state, conn, config)
    if state.current_inaccuracy_id is None:
        return InaccuracyStateOut(counts=counts)
    card = repo.get(conn, state.current_inaccuracy_id)
    if card is None:  # pragma: no cover
        state.reset_inaccuracy()
        return InaccuracyStateOut(counts=counts)
    return InaccuracyStateOut(
        card=_card_out(conn, card, CardSource.DUE),
        counts=counts,
        attempts=len(state.inaccuracy_attempts),
        hint=_hint_out(card) if state.inaccuracy_hinted else None,
        finished=state.inaccuracy_finished,
    )


@router.post("/next", response_model=InaccuracyStateOut)
def next_card(state: State, conn: Conn, config: Cfg) -> InaccuracyStateOut:
    """Serve the next card: a failed one whose turn has come, else the oldest due."""
    item: DeckItem | None = state.inaccuracy_deck.next_item(conn, _today(config))
    state.reset_inaccuracy()
    if item is None:
        return InaccuracyStateOut(counts=_counts(state, conn, config), exhausted=True)
    state.current_inaccuracy_id = item.card.id
    state.inaccuracy_deck.mark_served()
    return InaccuracyStateOut(
        card=_card_out(conn, item.card, item.source),
        counts=_counts(state, conn, config),
    )


@router.post("/hint", response_model=HintOut)
def hint(state: State, conn: Conn) -> HintOut:
    """The square and piece the answer moves -- not where it goes."""
    card = _current(state, conn)
    _require_open(state)
    state.inaccuracy_hinted = True
    return _hint_out(card)


@router.post("/attempt", response_model=InaccuracyAttemptResponse)
async def attempt(
    payload: CardAttemptRequest, state: State, conn: Conn, engine: Engine, config: Cfg
) -> InaccuracyAttemptResponse:
    """Try a move. Only the recorded engine move is correct; retries are unlimited."""
    card = _current(state, conn)
    _require_open(state)
    try:
        uci = rules.resolve_uci(
            card.fen, payload.from_square, payload.to_square, payload.promotion
        )
        move = rules.apply_move(card.fen, uci)
    except rules.IllegalMove as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    state.inaccuracy_attempts.append(uci)
    correct = uci == card.best_move_uci
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)
    response = InaccuracyAttemptResponse(
        correct=correct,
        uci=uci,
        san=move.san,
        evaluation=EvalOut.of(evaluation),
        fen_after=move.fen_after,
        attempts=len(state.inaccuracy_attempts),
        finished=correct,
    )
    if correct:
        _finish(state, conn, config, card, response, revealed=False)
    return response


@router.post("/show-answer", response_model=InaccuracyAttemptResponse)
async def show_answer(
    state: State, conn: Conn, engine: Engine, config: Cfg
) -> InaccuracyAttemptResponse:
    """Reveal the answer, which fails the card: it comes back later this session."""
    card = _current(state, conn)
    _require_open(state)
    state.inaccuracy_shown = True
    move = rules.apply_move(card.fen, card.best_move_uci)
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)
    response = InaccuracyAttemptResponse(
        correct=False,
        uci=card.best_move_uci,
        san=move.san,
        evaluation=EvalOut.of(evaluation),
        fen_after=move.fen_after,
        attempts=len(state.inaccuracy_attempts),
        finished=True,
    )
    _finish(state, conn, config, card, response, revealed=True)
    return response


async def _evaluate(state: State, conn: Conn, engine: Engine, fen: str, config: Config):
    def run():
        return analysis.analyse(conn, engine, fen, config.engine_depth).evaluation

    return await state.in_thread(run)


def _finish(
    state: State,
    conn: sqlite3.Connection,
    config: Config,
    card: InaccuracyCard,
    response: InaccuracyAttemptResponse,
    *,
    revealed: bool,
) -> None:
    """Grade and schedule the card, and count the step on its first answer."""
    state.inaccuracy_finished = True
    answer = state.inaccuracy_deck.record_answer(
        conn,
        card,
        attempts=len(state.inaccuracy_attempts),
        used_show_answer=state.inaccuracy_shown,
        used_hint=state.inaccuracy_hinted,
        today=_today(config),
    )
    response.result = _result_out(card, answer, revealed=revealed)
    response.counts = _counts(state, conn, config)

    # Like the opening cards: the first answer counts the step for the streak,
    # but the step stays on screen until the deck is empty.
    if Step.INACCURACY_CARDS not in state.flow.completed:
        state.flow.mark_completed(Step.INACCURACY_CARDS)
        streak = tracker.record_step(conn, tz_name=config.timezone)
        response.session = SessionOut.of(state.flow)
        response.streak = StreakOut.of(streak)
