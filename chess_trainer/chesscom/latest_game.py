"""Finding the most recent game.

Walks back through monthly archives so an empty current month (nothing played
yet this month) falls through to the previous one rather than reporting nothing.
"""

from __future__ import annotations

from chess_trainer.chesscom import archives, game_model
from chess_trainer.chesscom.client import ChessComClient, ChessComError
from chess_trainer.chesscom.game_model import ChessComGame

#: How many months to look back before giving up.
MAX_ARCHIVES_TO_SEARCH = 6


class NoGamesFound(ChessComError):
    """The player has no reviewable games in the months we searched."""


def most_recent(games: list[ChessComGame]) -> ChessComGame | None:
    """The newest game in a list.

    Archives arrive in chronological order, but sorting on ``end_time`` makes
    that assumption explicit. Games without an end time sort oldest.
    """
    if not games:
        return None
    return max(games, key=lambda game: (game.end_time or 0))


def newer_than(
    games: list[ChessComGame], game_id: str | None, end_time: int | None = None
) -> list[ChessComGame]:
    """Games strictly newer than a known one.

    With no reference game every game counts as new. Otherwise a game is new if
    it ended later than the reference, or has a different id and no earlier end
    time -- which covers chess.com reporting equal timestamps for games that
    finished in the same second.
    """
    if game_id is None:
        return list(games)
    reference = end_time or 0
    return [
        game
        for game in games
        if game.id != game_id and (game.end_time or 0) >= reference
    ]


def fetch_latest(
    client: ChessComClient,
    *,
    username: str | None = None,
    standard_only: bool = True,
    max_archives: int = MAX_ARCHIVES_TO_SEARCH,
) -> ChessComGame:
    """Fetch the player's most recent reviewable game.

    Raises :class:`NoGamesFound` when nothing suitable turns up.
    """
    player = username or client.username
    archive_urls = archives.sort_newest_first(client.archive_urls())
    if not archive_urls:
        raise NoGamesFound(f"{player} has no games on chess.com yet.")

    for archive_url in archive_urls[:max_archives]:
        games = game_model.parse_games(client.archive_games(archive_url))
        candidates = [g for g in games if g.played_by(player)]
        if standard_only:
            candidates = [g for g in candidates if g.is_standard]
        newest = most_recent(candidates)
        if newest is not None:
            return newest

    searched = min(len(archive_urls), max_archives)
    raise NoGamesFound(
        f"No reviewable games for {player} in the last {searched} month(s) of archives."
    )


def fetch_games_in_latest_archive(
    client: ChessComClient,
    *,
    username: str | None = None,
    standard_only: bool = True,
) -> list[ChessComGame]:
    """Every reviewable game in the newest non-empty archive.

    Used by the poller, which needs to compare against what it saw before
    rather than just take the newest.
    """
    player = username or client.username
    for archive_url in archives.sort_newest_first(client.archive_urls()):
        games = game_model.parse_games(client.archive_games(archive_url))
        candidates = [g for g in games if g.played_by(player)]
        if standard_only:
            candidates = [g for g in candidates if g.is_standard]
        if candidates:
            return candidates
    return []
