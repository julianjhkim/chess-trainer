"""Client tests driven by an httpx mock transport: no real network."""

from __future__ import annotations

import httpx
import pytest

from chess_trainer.chesscom.client import (
    ChessComClient,
    ChessComRateLimited,
    ChessComUnavailable,
    PlayerNotFound,
)

BASE = "https://api.chess.com/pub"
USER_AGENT = "chess-trainer/test (contact)"


def client_for(handler) -> ChessComClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, headers={"User-Agent": USER_AGENT})
    return ChessComClient("test-player", USER_AGENT, client=http)


def test_archive_urls_are_returned():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/pub/player/test-player/games/archives"
        return httpx.Response(200, json={"archives": [f"{BASE}/x/games/2026/10"]})

    assert client_for(handler).archive_urls() == [f"{BASE}/x/games/2026/10"]


def test_a_descriptive_user_agent_is_sent():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json={"archives": []})

    client_for(handler).archive_urls()
    assert seen and "chess-trainer" in seen[0]


def test_unknown_player_raises_player_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    with pytest.raises(PlayerNotFound, match="no player called"):
        client_for(handler).archive_urls()


def test_rate_limiting_is_distinguished():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    with pytest.raises(ChessComRateLimited, match="rate limiting"):
        client_for(handler).archive_urls()


def test_server_errors_become_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    with pytest.raises(ChessComUnavailable, match="HTTP 503"):
        client_for(handler).archive_urls()


def test_a_transport_failure_becomes_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(ChessComUnavailable, match="Could not reach"):
        client_for(handler).archive_urls()


def test_non_json_response_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>")

    with pytest.raises(ChessComUnavailable, match="non-JSON"):
        client_for(handler).archive_urls()


def test_a_json_list_instead_of_an_object_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(ChessComUnavailable, match="Unexpected response shape"):
        client_for(handler).archive_urls()


def test_missing_archives_key_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"something_else": []})

    with pytest.raises(ChessComUnavailable, match="Archive list was missing"):
        client_for(handler).archive_urls()


def test_non_string_archive_entries_are_dropped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"archives": ["https://a", 42, None]})

    assert client_for(handler).archive_urls() == ["https://a"]


def test_archive_games_returns_the_game_objects():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"games": [{"uuid": "a"}, {"uuid": "b"}]})

    games = client_for(handler).archive_games(f"{BASE}/x/games/2026/10")
    assert [g["uuid"] for g in games] == ["a", "b"]


def test_an_empty_month_returns_an_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"games": []})

    assert client_for(handler).archive_games(f"{BASE}/x/games/2026/10") == []


def test_a_month_with_no_games_key_returns_an_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert client_for(handler).archive_games(f"{BASE}/x/games/2026/10") == []


def test_non_dict_game_entries_are_dropped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"games": [{"uuid": "a"}, "junk"]})

    assert len(client_for(handler).archive_games(f"{BASE}/x")) == 1


def test_a_bad_games_shape_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"games": "not a list"})

    with pytest.raises(ChessComUnavailable, match="Unexpected 'games' shape"):
        client_for(handler).archive_games(f"{BASE}/x")


def test_username_is_trimmed():
    assert ChessComClient("  test-player  ", USER_AGENT).username == "test-player"


def test_the_client_can_be_used_as_a_context_manager():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"archives": []})

    with client_for(handler) as client:
        assert client.archive_urls() == []


def test_an_injected_client_is_not_closed_by_us():
    """We must not close a client we did not create."""
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client = ChessComClient("x", USER_AGENT, client=http)
    client.close()
    assert not http.is_closed
    http.close()
