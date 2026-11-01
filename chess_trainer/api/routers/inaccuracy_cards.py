"""Revision cards (internally "inaccuracy cards"): slips I pick, drilled again.

I make a card by pasting a game and naming the number of my move that went
wrong; the card is the position before it. The answer is the engine's top
move there at the analysis depth, found when the card is made (the same strict
top-1 everywhere in the app). Grading and scheduling are the opening
cards' modified SM-2; a hint caps the grade at q=3. A card that looks wrong
or useless can be deleted for good.
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
    NewCardOut,
    NewCardPreviewOut,
    NewCardRequest,
    GameMoveOut,
    SessionOut,
    StreakOut,
)
from chess_trainer.config import Config
from chess_trainer.db import games_repo, inaccuracy_cards_repo as repo, usernames_repo
from chess_trainer.db.inaccuracy_cards_repo import InaccuracyCard
from chess_trainer.engine import analysis
from chess_trainer.engine.classify import classify
from chess_trainer.engine.winpct import win_percent_drop
from chess_trainer.inaccuracies import deck as deck_module
from chess_trainer.inaccuracies import slip as slip_module
from chess_trainer.inaccuracies.deck import DeckAnswer, DeckItem
from chess_trainer.inaccuracies.lichess_link import analysis_url
from chess_trainer.pgn import my_side, parse
from chess_trainer.pgn import positions as positions_module
from chess_trainer.pgn.parse import ParsedGame, PgnParseError
from chess_trainer.pgn.positions import PositionMove
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


def _game_moves(conn: sqlite3.Connection, card: InaccuracyCard) -> list[PositionMove]:
    """The card's game, move by move -- or nothing if it is not stored (or no
    longer matches the card's position)."""
    game = games_repo.get(conn, card.game_id) if card.game_id else None
    if game is None:
        return []
    try:
        positions = positions_module.from_parsed(parse.parse_pgn(game.pgn))
    except (PgnParseError, ValueError):
        return []
    if card.ply >= len(positions):
        return []
    if slip_module.epd_of(positions[card.ply].fen_before) != card.epd:
        return []
    return positions


def _moves_out(positions: list[PositionMove], colour: str) -> list[GameMoveOut]:
    return [GameMoveOut.of(p, colour) for p in positions]


def _card_out(conn: sqlite3.Connection, card: InaccuracyCard, source: CardSource) -> InaccuracyCardOut:
    game = games_repo.get(conn, card.game_id) if card.game_id else None
    positions = _game_moves(conn, card)
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
        moves=_moves_out(positions[: card.ply], card.my_colour),
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


def _result_out(
    conn: sqlite3.Connection, card: InaccuracyCard, answer: DeckAnswer, *, revealed: bool
) -> InaccuracyResultOut:
    result = answer.result
    positions = _game_moves(conn, card)
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
        moves=_moves_out(positions, card.my_colour),
        ply=card.ply,
        lichess_url=analysis_url(
            positions,
            start_fen=positions[0].fen_before if positions else card.fen,
            ply=card.ply if positions else 0,
            my_colour=card.my_colour,
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


# -- making cards --------------------------------------------------------------
def _parse(payload: NewCardRequest) -> ParsedGame:
    try:
        return parse.parse_pgn(payload.pgn)
    except PgnParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _my_colour(
    conn: sqlite3.Connection, parsed: ParsedGame, payload: NewCardRequest, config: Config
) -> str:
    """The side I had: as asked, else found by my names (top bar) in the PGN."""
    if payload.colour is not None:
        return payload.colour
    names = usernames_repo.get(conn, seed=config.chesscom_username or None)
    colour = my_side.side_of(parsed, names)
    if colour is not None:
        return colour
    raise HTTPException(
        status_code=422,
        detail=(
            "Couldn't tell which side you played: none of your names (top right) "
            "is in this PGN. Pick White or Black, or add the name."
        ),
    )


def _slip(
    conn: sqlite3.Connection, payload: NewCardRequest, config: Config
) -> tuple[ParsedGame, str, list[PositionMove], PositionMove]:
    parsed = _parse(payload)
    colour = _my_colour(conn, parsed, payload, config)
    positions = positions_module.from_parsed(parsed)
    try:
        slip = slip_module.find_slip(
            positions, move_number=payload.move_number, my_colour=colour
        )
    except slip_module.SlipNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return parsed, colour, positions, slip


def _opponent(parsed: ParsedGame, colour: str) -> str | None:
    return parsed.black if colour == "white" else parsed.white


@router.post("/preview", response_model=NewCardPreviewOut)
def preview(payload: NewCardRequest, conn: Conn, config: Cfg) -> NewCardPreviewOut:
    """The position a card would drill: the moves up to my slip, and the slip."""
    parsed, colour, positions, slip = _slip(conn, payload, config)
    existing = repo.get_by_epd(conn, slip_module.epd_of(slip.fen_before))
    before = slip_module.moves_before(positions, slip)
    return NewCardPreviewOut(
        colour=colour,
        move_number=slip.move_number,
        ply=slip.ply,
        move_label=slip.move_label,
        my_move_uci=slip.uci,
        my_move_san=slip.san,
        fen=slip.fen_before,
        last_move_uci=before[-1].uci if before else None,
        opponent=_opponent(parsed, colour),
        moves=_moves_out(before, colour),
        existing="none" if existing is None else "deleted" if existing.deleted else "active",
    )


@router.post("", response_model=NewCardOut)
async def create(
    payload: NewCardRequest, state: State, conn: Conn, engine: Engine, config: Cfg
) -> NewCardOut:
    """Make a card from my slip. The engine names the answer; it is not shown.

    Refused when the engine's top move is the move I played: there would be
    nothing to find.
    """
    parsed, colour, positions, slip = _slip(conn, payload, config)
    depth = config.engine_depth

    def run():
        before = analysis.analyse(conn, engine, slip.fen_before, depth)
        after = analysis.analyse(conn, engine, slip.fen_after, depth)
        return before, after

    before, after = await state.in_thread(run)
    if before.best_move is None:
        raise HTTPException(status_code=422, detail="The engine has no move in that position.")
    if before.best_move == slip.uci:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Stockfish's top move here is the one you played ({slip.move_label}), "
                "so there is nothing to find. Check the move number."
            ),
        )

    drop = win_percent_drop(
        before.evaluation, after.evaluation, mover_is_white=slip.mover_is_white
    )
    game = games_repo.upsert(
        conn,
        games_repo.StoredGame(
            id=games_repo.paste_id(payload.pgn),
            pgn=payload.pgn,
            my_color=colour,
            url=parsed.headers.get("Link"),
            white_username=parsed.white,
            black_username=parsed.black,
            time_class=parsed.headers.get("TimeControl"),
            rules="chess",
            end_time=parse.end_time_of(parsed),
            source=games_repo.SOURCE_PASTE,
        ),
    )
    earlier = slip_module.moves_before(positions, slip)
    card = slip_module.card_for(
        slip,
        game_id=game.id,
        my_colour=colour,
        best_move_uci=before.best_move,
        classification=classify(drop).value,
        win_percent_drop=drop,
        depth=depth,
        previous=earlier[-1] if earlier else None,
    )
    added = deck_module.add_card(conn, card, today=_today(config))
    response = NewCardOut(
        move_label=added.card.move_label,
        due_on=added.due_on.isoformat(),
        created=added.created,
        restored=added.restored,
        counts=_counts(state, conn, config),
    )
    # Making a card completes the "Make a revision card" step (and counts the
    # day), but the step stays on screen so more cards can be made.
    if Step.MAKE_CARD not in state.flow.completed:
        state.flow.mark_completed(Step.MAKE_CARD)
        streak = tracker.record_step(conn, tz_name=config.timezone)
        response.session = SessionOut.of(state.flow)
        response.streak = StreakOut.of(streak)
    return response


@router.delete("/{card_id}", response_model=InaccuracyCountsOut)
def delete_card(card_id: int, state: State, conn: Conn, config: Cfg) -> InaccuracyCountsOut:
    """Delete a card: it is never due again (making it again restores it).

    Deleting the card on screen clears it, so the next step is to ask for the
    next card. Answers already given stay in the log (and in the streak).
    """
    card = repo.get(conn, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="No such card.")
    state.inaccuracy_deck.delete(conn, card_id)
    if state.current_inaccuracy_id == card_id:
        state.reset_inaccuracy()
    return _counts(state, conn, config)


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
    response.result = _result_out(conn, card, answer, revealed=revealed)
    response.counts = _counts(state, conn, config)

    # Like the opening cards: the first answer counts the step for the streak,
    # but the step stays on screen until the deck is empty.
    if Step.INACCURACY_CARDS not in state.flow.completed:
        state.flow.mark_completed(Step.INACCURACY_CARDS)
        streak = tracker.record_step(conn, tz_name=config.timezone)
        response.session = SessionOut.of(state.flow)
        response.streak = StreakOut.of(streak)
