"""Opening cards: serving them, answering them, and growing the tree."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from chess_trainer.api.deps import Cfg, Conn, Engine, Explorer, State
from chess_trainer.api.schemas import (
    CardAttemptRequest,
    CardAttemptResponse,
    CardGradeOut,
    CardOut,
    CardStateOut,
    DeadEndOut,
    EvalOut,
    QueueCountsOut,
    SessionOut,
    ShowCardAnswerResponse,
    StatsTableOut,
    StreakOut,
)
from chess_trainer import rules
from chess_trainer.config import Config
from chess_trainer.db import cards_repo, schedule_repo
from chess_trainer.db.cards_repo import CardRow
from chess_trainer.engine import analysis
from chess_trainer.explorer.explorer_types import PositionStats
from chess_trainer.explorer.lichess_client import ExplorerError
from chess_trainer.openings import card_builder, line as line_module, stats_table
from chess_trainer.openings.card_types import CardMode
from chess_trainer.openings.tree_rules import MIN_GAMES, describe_threshold
from chess_trainer.session.steps import Step
from chess_trainer.srs import grading
from chess_trainer.srs.due import CardSource
from chess_trainer.streak import seoul_day, tracker

router = APIRouter(prefix="/api/cards", tags=["cards"])


def _today(config: Config):
    return seoul_day.today(tz_name=config.timezone)


def _counts(state: State, conn: sqlite3.Connection, config: Config) -> QueueCountsOut:
    return QueueCountsOut.of(state.card_queue.counts(conn, _today(config)))


def _cached_engine_move(
    conn: sqlite3.Connection, card: CardRow, config: Config
) -> str | None:
    """Stockfish's move here, if it is already cached.

    This endpoint only reports what is on screen, so it reads the cache and
    never starts a search; the card was served with the search already done.
    """
    cached = analysis.cached_only(conn, card.fen, config.engine_depth)
    return cached.best_move if cached else None


def _current_card(state: State, conn: sqlite3.Connection) -> CardRow:
    if state.current_card_id is None:
        raise HTTPException(
            status_code=409, detail="No card is on screen. Ask for the next one first."
        )
    card = cards_repo.get(conn, state.current_card_id)
    if card is None:  # pragma: no cover - the card was deleted under us
        state.reset_card()
        raise HTTPException(status_code=409, detail="That card no longer exists.")
    return card


@router.get("/state", response_model=CardStateOut)
def get_state(state: State, conn: Conn, config: Cfg) -> CardStateOut:
    """The card on screen, if any, and what is queued behind it."""
    counts = _counts(state, conn, config)
    if state.current_card_id is None:
        return CardStateOut(card=None, counts=counts)

    card = cards_repo.get(conn, state.current_card_id)
    if card is None:  # pragma: no cover
        state.reset_card()
        return CardStateOut(card=None, counts=counts)

    return CardStateOut(
        card=CardOut.of(
            card,
            source=CardSource.DUE,
            schedule=schedule_repo.get(conn, card.id or 0),
            engine_best_uci=_cached_engine_move(conn, card, config),
        ),
        counts=counts,
        attempts=len(state.card_attempts),
        used_show_answer=state.card_shown,
        solved=state.card_finished and not state.card_shown,
        finished=state.card_finished,
    )


@router.post("/next", response_model=CardStateOut)
async def next_card(
    state: State, conn: Conn, explorer: Explorer, engine: Engine, config: Cfg
) -> CardStateOut:
    """Serve the next card: due reviews first, then new ones.

    The tree is bootstrapped on first use, and a card's answer is resolved the
    first time it is served -- both of which may call Lichess, so this runs off
    the event loop.
    """

    def run():
        card_builder.ensure_bootstrapped(conn, explorer)
        item = state.card_queue.next_item(conn, _today(config))
        if item is None:
            return None
        prepared = card_builder.prepare_card(
            conn, explorer, engine, item.card, engine_depth=config.engine_depth
        )
        return item, prepared

    try:
        outcome = await state.in_thread(run)
    except ExplorerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if outcome is None:
        state.reset_card()
        return CardStateOut(
            card=None, counts=_counts(state, conn, config), exhausted=True
        )

    item, prepared = outcome
    card = prepared.card

    # A card whose own record turns out too thin becomes a dead end; skip it
    # and serve the next one instead of showing an unanswerable card.
    if card.is_dead_end:
        state.reset_card()
        return await next_card(state, conn, explorer, engine, config)

    state.reset_card()
    state.current_card_id = card.id
    state.card_queue.mark_served()

    return CardStateOut(
        card=CardOut.of(
            card,
            source=item.source,
            schedule=item.schedule,
            engine_best_uci=prepared.engine_best_uci,
        ),
        counts=_counts(state, conn, config),
    )


@router.post("/attempt", response_model=CardAttemptResponse)
async def attempt(
    payload: CardAttemptRequest,
    state: State,
    conn: Conn,
    explorer: Explorer,
    engine: Engine,
    config: Cfg,
) -> CardAttemptResponse:
    """Try a move on the current card. Wrong answers are unlimited."""
    card = _current_card(state, conn)
    if state.card_finished:
        raise HTTPException(
            status_code=409, detail="This card is finished. Ask for the next one."
        )
    if card.answer_uci is None:  # pragma: no cover - prepared when served
        raise HTTPException(status_code=409, detail="This card has no answer yet.")

    try:
        move_uci = rules.resolve_uci(
            card.fen, payload.from_square, payload.to_square, payload.promotion
        )
        move = rules.apply_move(card.fen, move_uci)
    except rules.IllegalMove as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    state.card_attempts.append(move_uci)
    correct = move_uci == card.answer_uci
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)

    response = CardAttemptResponse(
        correct=correct,
        uci=move_uci,
        san=move.san,
        evaluation=EvalOut.of(evaluation),
        fen_after=move.fen_after,
        attempts=len(state.card_attempts),
        finished=correct,
    )

    if correct:
        await _finish_card(state, conn, explorer, engine, config, card, response)
    return response


@router.post("/show-answer", response_model=ShowCardAnswerResponse)
async def show_answer(
    state: State,
    conn: Conn,
    explorer: Explorer,
    engine: Engine,
    config: Cfg,
) -> ShowCardAnswerResponse:
    """Reveal the answer. Grades as a failure, so the card comes back."""
    card = _current_card(state, conn)
    if state.card_finished:
        raise HTTPException(
            status_code=409, detail="This card is finished. Ask for the next one."
        )
    if card.answer_uci is None:  # pragma: no cover
        raise HTTPException(status_code=409, detail="This card has no answer yet.")

    state.card_shown = True
    move = rules.apply_move(card.fen, card.answer_uci)
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)

    response = ShowCardAnswerResponse(
        answer_uci=card.answer_uci,
        answer_san=card.answer_san or move.san,
        fen_after=move.fen_after,
        evaluation=EvalOut.of(evaluation),
        attempts=len(state.card_attempts),
        stats=StatsTableOut(rows=[], total_games=0),
        grade=CardGradeOut(
            quality=grading.QUALITY_SHOWN,
            description=grading.describe(grading.QUALITY_SHOWN),
            passed=False,
            was_new=False,
            rescheduled=False,
            requeued=True,
        ),
        counts=_counts(state, conn, config),
    )
    await _finish_card(state, conn, explorer, engine, config, card, response)
    return response


async def _evaluate(state: State, conn: Conn, engine: Engine, fen: str, config: Config):
    def run():
        return analysis.analyse(conn, engine, fen, config.engine_depth).evaluation

    return await state.in_thread(run)


async def _finish_card(
    state: State,
    conn: sqlite3.Connection,
    explorer: Explorer,
    engine: Engine,
    config: Config,
    card: CardRow,
    response: CardAttemptResponse | ShowCardAnswerResponse,
) -> None:
    """Grade the card, schedule it, grow the tree, and build the report."""
    state.card_finished = True
    today = _today(config)

    def run():
        outcome = state.card_queue.record_answer(
            conn,
            card,
            attempts=len(state.card_attempts),
            used_show_answer=state.card_shown,
            today=today,
        )
        expansion = None
        # Branches appear only once the card has actually been got right.
        if outcome.passed and not card.is_expanded:
            expansion = card_builder.expand_card(
                conn, explorer, engine, card, engine_depth=config.engine_depth
            )
        stats = card_builder.stats_for_card(conn, explorer, card)
        engine_move = card_builder.engine_best_move(
            conn, engine, card, engine_depth=config.engine_depth
        )
        return outcome, expansion, stats, engine_move

    try:
        outcome, expansion, stats, engine_move = await state.in_thread(run)
    except ExplorerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # The question told the player whether the most played move was also the
    # engine's; the table marks both, so that can be checked against the moves.
    table = stats_table.build(
        stats,
        answer_uci=card.answer_uci,
        mode=CardMode(card.mode) if card.mode else None,
        tied_ucis=card.tied_ucis,
        engine_move_uci=engine_move,
        engine_move_san=(
            line_module.san_of(card.fen, engine_move) if engine_move else None
        ),
    )

    response.answer_uci = card.answer_uci
    response.answer_san = card.answer_san
    response.stats = StatsTableOut.of(table)
    response.grade = CardGradeOut.of(outcome)
    response.dead_ends = _dead_ends_out(conn, card, stats)
    response.branches_created = len(expansion.new_cards) if expansion else 0
    response.counts = _counts(state, conn, config)

    # The first card answered marks the step done for the streak, but the step
    # keeps running: opening cards have no end.
    if Step.CARDS not in state.flow.completed:
        state.flow.mark_completed(Step.CARDS)
        streak = tracker.record_step(conn, tz_name=config.timezone)
        response.session = SessionOut.of(state.flow)
        response.streak = StreakOut.of(streak)


def _dead_ends_out(
    conn: sqlite3.Connection, card: CardRow, stats: PositionStats
) -> list[DeadEndOut]:
    """"Max depth reached" entries for branches that stopped here.

    The stats come from this card's own record, which already holds the
    white/draw/black split for every branch move.
    """
    out: list[DeadEndOut] = []
    for child in cards_repo.dead_end_children(conn, card.id or 0):
        move = stats.move(child.given_move_uci)
        out.append(
            DeadEndOut(
                line_label=line_module.line_label(child.ucis),
                given_move_san=child.given_move_san,
                games=child.position_games,
                white=move.white if move else 0,
                draws=move.draws if move else 0,
                black=move.black if move else 0,
                average_rating=move.average_rating if move else None,
                detail=(
                    f"{describe_threshold(child.position_games)} "
                    f"— under {MIN_GAMES}, so this line stops here."
                ),
            )
        )
    return out
