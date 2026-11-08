"""Puzzles (internally "inaccuracy cards"): slips from my games, drilled again.

I make a card by pasting a game and naming the number of my move that went
wrong; the card is the position before it. The answer is the engine's top
move there at the analysis depth, found when the card is made (the same strict
top-1 everywhere in the app). Where the line after it is forcing, the card is
a puzzle (``inaccuracies.puzzle``): each right move brings the opponent's
reply, and I go on until the line ends. Grading counts wrong tries over the
whole puzzle, with the opening cards' modified SM-2; a hint caps the grade at
q=3. A card that looks wrong or useless can be deleted for good.
"""

from __future__ import annotations

import dataclasses
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
    FoundPuzzleOut,
    NewCardOut,
    NewCardPreviewOut,
    NewCardRequest,
    ScanOut,
    ScanRequest,
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
from chess_trainer.inaccuracies import puzzle
from chess_trainer.inaccuracies import scan as scan_module
from chess_trainer.api.scan_job import ScanJob
from chess_trainer.inaccuracies import slip as slip_module
from chess_trainer.inaccuracies.deck import DeckAnswer, DeckItem
from chess_trainer.pgn.lichess_link import analysis_url
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
    if card.ply > len(positions) or not positions:
        return []
    # A punishment can start after the game's last move (a mistake that lost).
    fen = positions[card.ply].fen_before if card.ply < len(positions) else positions[-1].fen_after
    if slip_module.epd_of(fen) != card.epd:
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
        orientation=card.solver,
        last_move_uci=card.last_move_uci,
        move_number=card.move_number,
        classification=card.classification,
        my_move_uci=None if card.punishes else card.my_move_uci,
        my_move_san=None if card.punishes else card.my_move_san,
        move_label=card.move_label,
        kind=card.kind,
        slip_mine=card.slip_mine,
        my_colour=card.my_colour,
        source=source.value,
        opponent=game.opponent if game else None,
        played_on=game.end_time if game else None,
        interval_days=schedule.interval_days if schedule else None,
        reps=schedule.reps if schedule else 0,
        moves=_moves_out(positions[: card.ply], card.my_colour),
    )


# -- the puzzle line ---------------------------------------------------------
def _line(card: InaccuracyCard) -> tuple[str, ...]:
    """The card's puzzle line; a card not yet worked out is just its answer."""
    return card.solution or (card.best_move_uci,)


def _line_moves(card: InaccuracyCard, line: tuple[str, ...]) -> list[GameMoveOut]:
    """Moves of the line, numbered as in the game (the slip is ply ``card.ply``)."""
    walked = positions_module.walk(list(line), start_fen=card.fen)
    return _moves_out(
        [dataclasses.replace(p, ply=card.ply + i) for i, p in enumerate(walked)],
        card.my_colour,
    )


def _fen_at(card: InaccuracyCard, plies: int) -> str:
    """The position after the first ``plies`` moves of the puzzle line."""
    if plies == 0:
        return card.fen
    return positions_module.walk(list(_line(card)[:plies]), start_fen=card.fen)[-1].fen_after


async def _with_puzzle(
    state: State, conn: sqlite3.Connection, engine: Engine, card: InaccuracyCard
) -> InaccuracyCard:
    """Work out the puzzle of a card made before puzzles existed."""
    if card.solution is not None:
        return card

    def run():
        line = puzzle.build_line(
            conn, engine, card.fen, card.depth, first_move=card.best_move_uci
        )
        return repo.set_solution(conn, card.id or 0, line)

    return await state.in_thread(run)


def _hint_out(state: State, card: InaccuracyCard) -> HintOut:
    """The piece to move at the step the puzzle has reached."""
    progress = state.inaccuracy_progress
    return HintOut.of(_fen_at(card, progress), _line(card)[progress][:2])


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
        my_move_uci=card.my_move_uci or None,
        my_move_san=card.my_move_san or None,
        move_label=card.move_label,
        classification=card.classification,
        win_percent_drop=card.win_percent_drop,
        revealed=revealed,
        kind=card.kind,
        slip_mine=card.slip_mine,
        played_label=(
            positions[card.ply].move_label
            if card.punishes and card.ply < len(positions)
            else None
        ),
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
        solution=_line_moves(card, _line(card)),
        lichess_url=analysis_url(
            positions,
            start_fen=positions[0].fen_before if positions else card.fen,
            ply=card.ply if positions else 0,
            my_colour=card.solver,
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
        hint=_hint_out(state, card) if state.inaccuracy_hinted else None,
        finished=state.inaccuracy_finished,
    )


@router.post("/next", response_model=InaccuracyStateOut)
async def next_card(
    state: State, conn: Conn, engine: Engine, config: Cfg
) -> InaccuracyStateOut:
    """Serve the next card: a failed one whose turn has come, else the oldest due.

    A card made before puzzles gets its puzzle worked out here, once.
    """
    item: DeckItem | None = state.inaccuracy_deck.next_item(conn, _today(config))
    state.reset_inaccuracy()
    if item is None:
        return InaccuracyStateOut(counts=_counts(state, conn, config), exhausted=True)
    card = await _with_puzzle(state, conn, engine, item.card)
    state.current_inaccuracy_id = card.id
    state.inaccuracy_deck.mark_served()
    return InaccuracyStateOut(
        card=_card_out(conn, card, item.source),
        counts=_counts(state, conn, config),
    )


@router.post("/hint", response_model=HintOut)
def hint(state: State, conn: Conn) -> HintOut:
    """The square and piece the answer moves -- not where it goes."""
    card = _current(state, conn)
    _require_open(state)
    state.inaccuracy_hinted = True
    return _hint_out(state, card)


@router.post("/attempt", response_model=InaccuracyAttemptResponse)
async def attempt(
    payload: CardAttemptRequest, state: State, conn: Conn, engine: Engine, config: Cfg
) -> InaccuracyAttemptResponse:
    """Try a move at the step the puzzle has reached; retries are unlimited.

    Only the engine's move is right (or, where it mates, any mate). A right
    move with more to come plays the opponent's reply and waits for my next.
    """
    card = _current(state, conn)
    _require_open(state)
    line = _line(card)
    progress = state.inaccuracy_progress
    fen = _fen_at(card, progress)
    try:
        uci = rules.resolve_uci(fen, payload.from_square, payload.to_square, payload.promotion)
        move = rules.apply_move(fen, uci)
    except rules.IllegalMove as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    state.inaccuracy_attempts.append(uci)
    correct = puzzle.accepts(fen, line[progress], uci)
    if not correct:
        state.inaccuracy_wrong += 1
    finished = correct and progress + 1 >= len(line)
    evaluation = await _evaluate(state, conn, engine, move.fen_after, config)
    response = InaccuracyAttemptResponse(
        correct=correct,
        uci=uci,
        san=move.san,
        evaluation=EvalOut.of(evaluation),
        fen_after=move.fen_after,
        attempts=len(state.inaccuracy_attempts),
        finished=finished,
    )
    if finished:
        state.inaccuracy_progress = progress + 1
        _finish(state, conn, config, card, response, revealed=False)
    elif correct:
        state.inaccuracy_progress = progress + 2
        played = _line_moves(card, line[: progress + 2])[progress:]
        response.played = played
        response.reply_san = played[-1].san
        response.fen_after_reply = played[-1].fen_after
    return response


@router.post("/show-answer", response_model=InaccuracyAttemptResponse)
async def show_answer(
    state: State, conn: Conn, engine: Engine, config: Cfg
) -> InaccuracyAttemptResponse:
    """Reveal the rest of the puzzle, which fails the card: it comes back later
    this session."""
    card = _current(state, conn)
    _require_open(state)
    state.inaccuracy_shown = True
    line = _line(card)
    progress = state.inaccuracy_progress
    fen = _fen_at(card, progress)
    move = rules.apply_move(fen, line[progress])
    end = _fen_at(card, len(line))
    evaluation = await _evaluate(state, conn, engine, end, config)
    state.inaccuracy_progress = len(line)
    response = InaccuracyAttemptResponse(
        correct=False,
        uci=line[progress],
        san=move.san,
        evaluation=EvalOut.of(evaluation),
        fen_after=end,
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
        line = None
        if before.best_move is not None and before.best_move != slip.uci:
            line = puzzle.build_line(
                conn, engine, slip.fen_before, depth, first_move=before.best_move
            )
        return before, after, line

    before, after, line = await state.in_thread(run)
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
    game = _store_game(conn, payload.pgn, parsed, colour)
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
    card = dataclasses.replace(card, solution=line)
    added = deck_module.add_card(conn, card, today=_today(config))
    if added.card.solution is None and added.card.best_move_uci == card.best_move_uci:
        repo.set_solution(conn, added.card.id or 0, line)
    response = NewCardOut(
        move_label=added.card.move_label,
        due_on=added.due_on.isoformat(),
        created=added.created,
        restored=added.restored,
        counts=_counts(state, conn, config),
    )
    # Making a card completes the "Make puzzles" step (and counts the
    # day), but the step stays on screen so more cards can be made.
    if Step.MAKE_CARD not in state.flow.completed:
        state.flow.mark_completed(Step.MAKE_CARD)
        streak = tracker.record_step(conn, tz_name=config.timezone)
        response.session = SessionOut.of(state.flow)
        response.streak = StreakOut.of(streak)
    return response


def _store_game(conn: sqlite3.Connection, pgn: str, parsed: ParsedGame, colour: str):
    """Keep the pasted game, so its cards can show the moves."""
    return games_repo.upsert(
        conn,
        games_repo.StoredGame(
            id=games_repo.paste_id(pgn),
            pgn=pgn,
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


# -- scanning a game for puzzles ---------------------------------------------
class _ScanOutcome:
    def __init__(self, colour, positions, result, saved) -> None:
        self.colour = colour
        self.positions = positions
        self.result = result
        #: (found puzzle, what adding it did), in game order.
        self.saved = saved


@router.post("/scan", response_model=ScanOut)
def start_scan(
    payload: ScanRequest, state: State, conn: Conn, engine: Engine, config: Cfg
) -> ScanOut:
    """Scan a pasted game for puzzles, in the background; poll ``GET /scan``.

    Every move is checked, both sides'; each mistake with a single clear
    punishment becomes a puzzle, due the next day.
    """
    if state.scan_job is not None and state.scan_job.running:
        raise HTTPException(status_code=409, detail="A game is already being scanned.")
    parsed = _parse(payload)
    colour = _my_colour(conn, parsed, payload, config)
    positions = positions_module.from_parsed(parsed)
    if not positions:
        raise HTTPException(status_code=422, detail="That game has no moves.")
    depth = config.engine_depth

    def work(job: ScanJob) -> _ScanOutcome:
        result = scan_module.scan_game(
            conn, engine, positions, colour, depth,
            on_progress=job.progress, cancelled=lambda: job.cancelled,
        )
        saved = _save_found(conn, config, payload.pgn, parsed, colour, positions, result)
        return _ScanOutcome(colour, positions, result, saved)

    job = ScanJob(work)
    job.progress(0, len(positions))
    state.scan_job = job.start()
    return _scan_out(state, conn, config)


@router.get("/scan", response_model=ScanOut)
def scan_state(state: State, conn: Conn, config: Cfg) -> ScanOut:
    """How the latest scan is going; once done, the puzzles it saved."""
    return _scan_out(state, conn, config)


@router.delete("/scan", response_model=ScanOut)
async def cancel_scan(state: State, conn: Conn, config: Cfg) -> ScanOut:
    """Stop the scan (after the move being checked). Nothing is saved."""
    if state.scan_job is not None and state.scan_job.running:
        await state.in_thread(state.scan_job.cancel)
    return _scan_out(state, conn, config)


def _save_found(conn, config, pgn, parsed, colour, positions, result):
    if not result.found:
        return []
    game = _store_game(conn, pgn, parsed, colour)
    saved = []
    for found in result.found:
        slip = found.slip
        card = slip_module.punishment_card_for(
            slip,
            next_move=positions[slip.ply + 1] if slip.ply + 1 < len(positions) else None,
            game_id=game.id,
            my_colour=colour,
            solver_colour=found.solver_colour,
            mine=found.mine,
            line=found.line,
            classification=found.classification,
            win_percent_drop=found.win_percent_drop,
            depth=config.engine_depth,
        )
        added = deck_module.add_card(conn, card, today=_today(config))
        saved.append((found, added))
    return saved


def _scan_out(state: State, conn: sqlite3.Connection, config: Config) -> ScanOut:
    job = state.scan_job
    if job is None:
        return ScanOut(status="idle")
    out = ScanOut(status=job.status, done=job.done, total=job.total, error=job.error)
    outcome: _ScanOutcome | None = job.result
    if job.status != "done" or outcome is None:
        return out
    out.colour = outcome.colour
    out.moves = _moves_out(outcome.positions, outcome.colour)
    out.skipped = [move.move_label for move in outcome.result.skipped]
    out.found = [
        FoundPuzzleOut(
            move_label=found.slip.move_label,
            slip_mine=found.mine,
            solver_colour=found.solver_colour,
            ply=found.slip.ply + 1,
            classification=found.classification,
            win_percent_drop=found.win_percent_drop,
            solver_moves=found.solver_moves,
            created=added.created,
            restored=added.restored,
            due_on=added.due_on.isoformat(),
        )
        for found, added in outcome.saved
    ]
    out.counts = _counts(state, conn, config)
    # Saving puzzles completes "Make puzzles" (and counts the day) -- once.
    if outcome.saved and not job.reported and Step.MAKE_CARD not in state.flow.completed:
        state.flow.mark_completed(Step.MAKE_CARD)
        streak = tracker.record_step(conn, tz_name=config.timezone)
        out.session = SessionOut.of(state.flow)
        out.streak = StreakOut.of(streak)
    job.reported = True
    return out


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
    # Graded on wrong tries over the whole puzzle: none is "first time".
    answer = state.inaccuracy_deck.record_answer(
        conn,
        card,
        attempts=state.inaccuracy_wrong + 1,
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
