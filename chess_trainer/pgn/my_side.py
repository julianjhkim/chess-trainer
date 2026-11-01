"""Which side I played in a game, from the names I go by.

I may play under more than one name (a chess.com account, a Lichess one, a new
account later), so the app keeps a list and a game is mine if either player's
name is on it -- compared case-insensitively, as chess.com and Lichess do.

Pure: names and a parsed game in, a colour (or None) out.
"""

from __future__ import annotations

from chess_trainer.pgn.parse import ParsedGame

#: Longest name accepted; chess.com allows 25 characters, Lichess 20.
MAX_NAME_LENGTH = 50
#: More names than anyone needs, but a bound all the same.
MAX_NAMES = 20


def normalise(names: list[str]) -> list[str]:
    """Trimmed, non-empty, without case-insensitive repeats, in the order given."""
    seen: set[str] = set()
    kept: list[str] = []
    for name in names:
        cleaned = name.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    return kept


def side_of(parsed: ParsedGame, names: list[str]) -> str | None:
    """"white" or "black" if exactly one player is me; None if neither or both."""
    mine = {name.lower() for name in names}
    white = (parsed.white or "").strip().lower() in mine
    black = (parsed.black or "").strip().lower() in mine
    if white == black:
        return None
    return "white" if white else "black"
