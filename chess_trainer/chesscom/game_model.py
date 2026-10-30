"""Parsing a chess.com game object into something typed.

Pure: hand it the decoded JSON and it tells you what the game was and which
colour a given player had. No network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

WHITE = "white"
BLACK = "black"

#: ``rules`` value for ordinary chess; anything else (bughouse, chess960, ...)
#: cannot be reviewed against a standard engine.
STANDARD_RULES = "chess"


class NotMyGame(ValueError):
    """Raised when neither player in a game is the configured user."""


@dataclass(frozen=True, slots=True)
class ChessComGame:
    """One game as the chess.com archive describes it."""

    id: str
    pgn: str
    url: str | None = None
    white_username: str | None = None
    black_username: str | None = None
    white_result: str | None = None
    black_result: str | None = None
    time_class: str | None = None
    rules: str | None = None
    end_time: int | None = None

    @property
    def is_standard(self) -> bool:
        """Whether this is ordinary chess, and so reviewable."""
        return (self.rules or STANDARD_RULES) == STANDARD_RULES

    def colour_of(self, username: str) -> str:
        """Which colour ``username`` played. Usernames compare case-insensitively."""
        wanted = username.strip().lower()
        if (self.white_username or "").lower() == wanted:
            return WHITE
        if (self.black_username or "").lower() == wanted:
            return BLACK
        raise NotMyGame(
            f"{username!r} did not play in this game "
            f"({self.white_username} vs {self.black_username})"
        )

    def played_by(self, username: str) -> bool:
        try:
            self.colour_of(username)
        except NotMyGame:
            return False
        return True


def game_id(payload: dict[str, Any]) -> str:
    """A stable id for a game.

    Prefers chess.com's ``uuid``, then the last path segment of the game URL,
    and finally a digest of the PGN, so a game is never stored twice.
    """
    uuid = payload.get("uuid")
    if isinstance(uuid, str) and uuid.strip():
        return uuid.strip()

    url = payload.get("url")
    if isinstance(url, str) and url.strip("/"):
        return url.strip("/").rsplit("/", 1)[-1]

    pgn = payload.get("pgn") or ""
    return "pgn-" + hashlib.sha256(pgn.encode("utf-8")).hexdigest()[:24]


def _player(payload: dict[str, Any], side: str, field: str) -> str | None:
    player = payload.get(side)
    if not isinstance(player, dict):
        return None
    value = player.get(field)
    return value if isinstance(value, str) else None


def parse_game(payload: dict[str, Any]) -> ChessComGame:
    """Build a :class:`ChessComGame` from one archive entry.

    Raises ``ValueError`` when the entry carries no PGN, which happens for
    games still in progress.
    """
    pgn = payload.get("pgn")
    if not isinstance(pgn, str) or not pgn.strip():
        raise ValueError("chess.com game has no PGN (is it still in progress?)")

    end_time = payload.get("end_time")
    return ChessComGame(
        id=game_id(payload),
        pgn=pgn,
        url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        white_username=_player(payload, "white", "username"),
        black_username=_player(payload, "black", "username"),
        white_result=_player(payload, "white", "result"),
        black_result=_player(payload, "black", "result"),
        time_class=payload.get("time_class"),
        rules=payload.get("rules"),
        end_time=int(end_time) if isinstance(end_time, (int, float)) else None,
    )


def parse_games(payloads: list[dict[str, Any]]) -> list[ChessComGame]:
    """Parse an archive's games, skipping entries without a PGN."""
    games: list[ChessComGame] = []
    for payload in payloads:
        try:
            games.append(parse_game(payload))
        except ValueError:
            continue
    return games
