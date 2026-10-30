from __future__ import annotations

from chess_trainer.chesscom import archives

BASE = "https://api.chess.com/pub/player/test-player/games"


def test_parse_month_reads_year_and_month():
    assert archives.parse_month(f"{BASE}/2026/10") == (2026, 10)


def test_parse_month_tolerates_a_trailing_slash():
    assert archives.parse_month(f"{BASE}/2026/10/") == (2026, 10)


def test_parse_month_tolerates_surrounding_whitespace():
    assert archives.parse_month(f"  {BASE}/2026/01  ") == (2026, 1)


def test_parse_month_rejects_a_non_archive_url():
    assert archives.parse_month("https://api.chess.com/pub/player/x") is None
    assert archives.parse_month("") is None


def test_sort_newest_first_orders_by_month():
    urls = [f"{BASE}/2025/12", f"{BASE}/2026/10", f"{BASE}/2026/02"]
    assert archives.sort_newest_first(urls) == [
        f"{BASE}/2026/10",
        f"{BASE}/2026/02",
        f"{BASE}/2025/12",
    ]


def test_sort_newest_first_crosses_the_year_boundary():
    urls = [f"{BASE}/2026/01", f"{BASE}/2025/11", f"{BASE}/2025/12"]
    assert archives.sort_newest_first(urls)[0] == f"{BASE}/2026/01"


def test_sort_is_not_fooled_by_api_ordering():
    """Sorting on the parsed month, not the given order."""
    urls = [f"{BASE}/2026/10", f"{BASE}/2025/01"]
    assert archives.sort_newest_first(urls)[0] == f"{BASE}/2026/10"


def test_unparseable_urls_sort_last():
    urls = [f"{BASE}/2026/10", "https://example.com/nonsense"]
    assert archives.sort_newest_first(urls)[-1] == "https://example.com/nonsense"


def test_latest_picks_the_newest():
    urls = [f"{BASE}/2025/12", f"{BASE}/2026/10"]
    assert archives.latest(urls) == f"{BASE}/2026/10"


def test_latest_of_nothing_is_none():
    assert archives.latest([]) is None


def test_sort_does_not_mutate_the_input():
    urls = [f"{BASE}/2025/12", f"{BASE}/2026/10"]
    archives.sort_newest_first(urls)
    assert urls == [f"{BASE}/2025/12", f"{BASE}/2026/10"]
