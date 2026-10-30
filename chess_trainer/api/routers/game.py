"""Getting a game to review: from chess.com, by polling, or pasted as PGN."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from chess_trainer.api.deps import Cfg, ChessCom, Conn, State
from chess_trainer.api.schemas import (
    GameOut,
    GameResponse,
    LatestGameResponse,
    PastePgnRequest,
    PollRequest,
    PollResponse,
)
from chess_trainer.chesscom import latest_game, polling
from chess_trainer.chesscom.client import ChessComClient, ChessComError
from chess_trainer.chesscom.game_model import ChessComGame, NotMyGame
from chess_trainer.config import Config
from chess_trainer.db import games_repo, state_repo
from chess_trainer.pgn import parse
from chess_trainer.pgn.parse import PgnParseError, PlayerNotInGame

router = APIRouter(prefix="/api/game", tags=["game"])


def _store_chesscom_game(
    conn: sqlite3.Connection, game: ChessComGame, username: str
) -> games_repo.StoredGame:
    """Persist a fetched game and remember it as the newest one we have seen."""
    try:
        colour = game.colour_of(username)
    except NotMyGame as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stored = games_repo.upsert(
        conn,
        games_repo.StoredGame(
            id=game.id,
            pgn=game.pgn,
            my_color=colour,
            url=game.url,
            white_username=game.white_username,
            black_username=game.black_username,
            white_result=game.white_result,
            black_result=game.black_result,
            time_class=game.time_class,
            rules=game.rules,
            end_time=game.end_time,
            source=games_repo.SOURCE_CHESSCOM,
        ),
    )
    state_repo.set_last_seen_game_id(conn, stored.id)
    return stored


def _move_count(pgn: str) -> int | None:
    try:
        return parse.parse_pgn(pgn).move_count
    except PgnParseError:
        return None


def _fetch_games(client: ChessComClient, username: str):
    def fetch():
        return latest_game.fetch_games_in_latest_archive(client, username=username)

    return fetch


@router.get("/latest", response_model=LatestGameResponse)
def latest_stored(conn: Conn) -> LatestGameResponse:
    """The most recent game we already hold, without touching the network."""
    game = games_repo.latest(conn)
    if game is None:
        return LatestGameResponse(game=None)
    return LatestGameResponse(game=GameOut.of(game, move_count=_move_count(game.pgn)))


@router.post("/fetch-latest", response_model=GameResponse)
async def fetch_latest(
    state: State, conn: Conn, client: ChessCom, config: Cfg
) -> GameResponse:
    """Fetch my most recent game from chess.com and store it."""

    def run() -> games_repo.StoredGame:
        game = latest_game.fetch_latest(client, username=config.chesscom_username)
        return _store_chesscom_game(conn, game, config.chesscom_username)

    try:
        stored = await state.in_thread(run)
    except ChessComError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return GameResponse(
        game=GameOut.of(stored, move_count=_move_count(stored.pgn))
    )


@router.post("/baseline", response_model=LatestGameResponse)
async def baseline(
    state: State, conn: Conn, client: ChessCom, config: Cfg
) -> LatestGameResponse:
    """Record what the newest game is *before* I go and play one.

    Step 2 waits for a game newer than this. Called when the play step opens, so
    the comparison works even when step 1 was skipped. A chess.com outage here
    is not fatal: with no baseline, polling accepts whatever the newest game is.
    """

    def run() -> games_repo.StoredGame | None:
        try:
            game = latest_game.fetch_latest(client, username=config.chesscom_username)
        except ChessComError:
            return None
        return _store_chesscom_game(conn, game, config.chesscom_username)

    stored = await state.in_thread(run)
    if stored is None:
        return LatestGameResponse(game=None)
    return LatestGameResponse(
        game=GameOut.of(stored, move_count=_move_count(stored.pgn))
    )


@router.post("/poll-new", response_model=PollResponse)
async def poll_new(
    payload: PollRequest, state: State, conn: Conn, client: ChessCom, config: Cfg
) -> PollResponse:
    """Wait a short while for a game newer than the last one seen.

    One call is a single window (about 12 seconds); the browser repeats it until
    the ~2 minute budget in the spec is spent. That way the UI can count down
    instead of hanging on one very long request.
    """
    budget = payload.budget_seconds or polling.WINDOW_SECONDS
    last_seen_id = state_repo.get_last_seen_game_id(conn)
    previous = games_repo.get(conn, last_seen_id) if last_seen_id else None

    def run() -> polling.PollResult:
        return polling.poll_for_new_game(
            _fetch_games(client, config.chesscom_username),
            last_seen_id=last_seen_id,
            last_seen_end_time=previous.end_time if previous else None,
            budget_seconds=budget,
        )

    try:
        result = await state.in_thread(run)
    except ChessComError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    game_out = None
    if result.game is not None:
        stored = _store_chesscom_game(conn, result.game, config.chesscom_username)
        game_out = GameOut.of(stored, move_count=_move_count(stored.pgn))

    return PollResponse(
        found=result.found,
        game=game_out,
        attempts=result.attempts,
        waited=result.waited,
        error=result.error,
        total_budget_seconds=polling.TOTAL_BUDGET_SECONDS,
    )


@router.post("/paste", response_model=GameResponse)
def paste_pgn(payload: PastePgnRequest, conn: Conn, config: Cfg) -> GameResponse:
    """Store a game from pasted PGN, the fallback for both review steps."""
    try:
        parsed = parse.parse_pgn(payload.pgn)
    except PgnParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    colour = _colour_from_pgn(parsed, config)
    stored = games_repo.upsert(
        conn,
        games_repo.StoredGame(
            id=_paste_id(payload.pgn),
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
    state_repo.set_last_seen_game_id(conn, stored.id)
    return GameResponse(game=GameOut.of(stored, move_count=parsed.move_count))


def _colour_from_pgn(parsed: parse.ParsedGame, config: Config) -> str:
    """Which side I had in a pasted game.

    Normally the PGN names me. If it does not -- someone else's game, or a
    study -- default to White rather than refusing, since the drill still works.
    """
    try:
        return parsed.colour_of(config.chesscom_username)
    except PlayerNotInGame:
        return "white"


def _paste_id(pgn: str) -> str:
    import hashlib

    digest = hashlib.sha256(pgn.strip().encode("utf-8")).hexdigest()[:24]
    return f"paste-{digest}"
