"""Choosing which monthly archive to read.

The archives endpoint returns URLs like
``https://api.chess.com/pub/player/<user>/games/2026/10``, oldest first. Pure
functions only; fetching lives in :mod:`chess_trainer.chesscom.client`.
"""

from __future__ import annotations

import re

#: Matches the year and month at the end of an archive URL.
ARCHIVE_PATTERN = re.compile(r"/(?P<year>\d{4})/(?P<month>\d{2})/?$")


def parse_month(url: str) -> tuple[int, int] | None:
    """Extract ``(year, month)`` from an archive URL, or ``None`` if it is odd."""
    match = ARCHIVE_PATTERN.search(url.strip())
    if match is None:
        return None
    return int(match["year"]), int(match["month"])


def sort_newest_first(urls: list[str]) -> list[str]:
    """Archive URLs ordered newest month first.

    The API already returns them oldest first, but sorting on the parsed month
    rather than trusting the order means a surprise cannot silently pick the
    wrong month. URLs that do not parse sort last.
    """

    def key(url: str) -> tuple[int, int]:
        month = parse_month(url)
        return month if month is not None else (-1, -1)

    return sorted(urls, key=key, reverse=True)


def latest(urls: list[str]) -> str | None:
    """The newest monthly archive URL, or ``None`` when there are none."""
    ordered = sort_newest_first(urls)
    return ordered[0] if ordered else None
