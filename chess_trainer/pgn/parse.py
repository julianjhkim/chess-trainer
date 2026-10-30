"""Turning PGN text into a typed game.

Pure: no network, no database. Used both for games fetched from chess.com and
for PGN pasted into the browser as a fallback.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

import chess
import chess.pgn

WHITE = "white"
BLACK = "black"


class PgnParseError(ValueError):
    """The PGN could not be read as a game."""


class PlayerNotInGame(ValueError):
    """Neither player in the PGN is the configured user."""


@dataclass(frozen=True, slots=True)
class ParsedGame:
    """A PGN reduced to what a review needs."""

    ucis: list[str]
    sans: list[str]
    headers: dict[str, str] = field(default_factory=dict)
    start_fen: str = chess.STARTING_FEN

    @property
    def white(self) -> str | None:
        return self.headers.get("White")

    @property
    def black(self) -> str | None:
        return self.headers.get("Black")

    @property
    def result(self) -> str | None:
        return self.headers.get("Result")

    @property
    def url(self) -> str | None:
        return self.headers.get("Link") or self.headers.get("Site") or None

    @property
    def move_count(self) -> int:
        return len(self.ucis)

    def colour_of(self, username: str) -> str:
        """Which colour ``username`` played, comparing case-insensitively."""
        wanted = username.strip().lower()
        if (self.white or "").lower() == wanted:
            return WHITE
        if (self.black or "").lower() == wanted:
            return BLACK
        raise PlayerNotInGame(
            f"{username!r} did not play in this game ({self.white} vs {self.black})"
        )

    def played_by(self, username: str) -> bool:
        try:
            self.colour_of(username)
        except PlayerNotInGame:
            return False
        return True


def parse_pgn(text: str) -> ParsedGame:
    """Parse PGN text into a :class:`ParsedGame`.

    Comments, clock annotations and variations are all tolerated; only the main
    line is kept, which is what a review walks.
    """
    if not text or not text.strip():
        raise PgnParseError("No PGN was provided.")

    try:
        game = chess.pgn.read_game(io.StringIO(text))
    except Exception as exc:  # python-chess can raise a variety of errors here
        raise PgnParseError(f"Could not read the PGN: {exc}") from exc

    if game is None:
        raise PgnParseError(
            "That does not look like a PGN. Paste the whole game, including the "
            "move list."
        )

    # python-chess does not stop at a move it cannot play: it truncates the
    # game there and records the problem. Silently reviewing a shortened game
    # would be worse than refusing, so surface it.
    if game.errors:
        first = game.errors[0]
        raise PgnParseError(
            f"The PGN could not be read in full: {first}. "
            "Check that it was copied complete and unmodified."
        )

    headers = {key: value for key, value in game.headers.items()}

    # A game may legitimately start from a set-up position.
    start_fen = headers.get("FEN", chess.STARTING_FEN)
    try:
        board = chess.Board(start_fen)
    except ValueError as exc:
        raise PgnParseError(f"The PGN's FEN header is invalid: {exc}") from exc

    ucis: list[str] = []
    sans: list[str] = []
    for move in game.mainline_moves():
        if move not in board.legal_moves:
            raise PgnParseError(
                f"The PGN contains an illegal move ({move.uci()}) at move "
                f"{board.fullmove_number}."
            )
        sans.append(board.san(move))
        ucis.append(move.uci())
        board.push(move)

    if not ucis:
        raise PgnParseError("That PGN contains no moves.")

    return ParsedGame(ucis=ucis, sans=sans, headers=headers, start_fen=start_fen)


def end_time_of(parsed: ParsedGame) -> int | None:
    """When the game finished, as a unix timestamp, if the PGN says.

    chess.com writes ``UTCDate``/``UTCTime`` and ``EndDate``/``EndTime``; plain
    PGN may only have ``Date``.
    """
    pairs = (
        ("EndDate", "EndTime"),
        ("UTCDate", "UTCTime"),
        ("Date", "StartTime"),
    )
    for date_key, time_key in pairs:
        date_value = parsed.headers.get(date_key)
        if not date_value or "?" in date_value:
            continue
        time_value = parsed.headers.get(time_key) or "00:00:00"
        for time_format in ("%H:%M:%S", "%H:%M"):
            try:
                moment = datetime.strptime(
                    f"{date_value} {time_value}", f"%Y.%m.%d {time_format}"
                )
            except ValueError:
                continue
            return int(moment.replace(tzinfo=timezone.utc).timestamp())
    return None
