"""Explorer client tests against a mock transport: no real network."""

from __future__ import annotations

import httpx
import pytest

from chess_trainer.explorer.lichess_client import (
    ExplorerRateLimited,
    ExplorerTokenMissing,
    ExplorerTokenRejected,
    ExplorerUnavailable,
    LichessExplorerClient,
)
from chess_trainer.explorer.rate_limit import Throttle

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
UA = "chess-trainer/test"


def no_wait_throttle() -> Throttle:
    return Throttle(min_interval=0.0, sleep=lambda _s: None, monotonic=lambda: 0.0)


def client_for(handler, *, token: str | None = "lip_token", **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return LichessExplorerClient(
        token, UA, client=http, throttle=no_wait_throttle(), **kwargs
    )


def ok(payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload or {"white": 1, "draws": 0, "black": 0})

    return handler


def test_a_successful_fetch_returns_the_payload():
    payload = {"white": 10, "draws": 5, "black": 2, "moves": []}
    assert client_for(ok(payload)).masters(START_FEN) == payload


def test_the_token_is_sent_as_a_bearer():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"white": 0, "draws": 0, "black": 0})

    client_for(handler, token="lip_abc").masters(START_FEN)
    assert seen == ["Bearer lip_abc"]


def test_a_descriptive_user_agent_is_sent():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json={"white": 0, "draws": 0, "black": 0})

    client_for(handler).masters(START_FEN)
    assert "chess-trainer" in seen[0]


def test_the_position_and_move_limit_are_sent():
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"white": 0, "draws": 0, "black": 0})

    client_for(handler).masters(START_FEN)
    assert seen[0].params["fen"] == START_FEN
    assert int(seen[0].params["moves"]) >= 20
    assert seen[0].params["topGames"] == "0"


def test_no_token_is_reported_with_instructions():
    client = LichessExplorerClient(None, UA, throttle=no_wait_throttle())
    assert not client.has_token
    with pytest.raises(ExplorerTokenMissing, match="needs an API token"):
        client.masters(START_FEN)


def test_a_blank_token_counts_as_missing():
    assert not LichessExplorerClient("   ", UA).has_token


def test_a_rejected_token_says_how_to_make_one():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(ExplorerTokenRejected, match="oauth/token/create"):
        client_for(handler).masters(START_FEN)


def test_a_forbidden_token_is_also_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(ExplorerTokenRejected):
        client_for(handler).masters(START_FEN)


def test_a_rate_limit_is_retried_once_then_succeeds():
    """The spec wants a 60s wait and a retry after an HTTP 429."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"white": 1, "draws": 0, "black": 0})

    client = client_for(handler)
    assert client.masters(START_FEN)["white"] == 1
    assert calls["n"] == 2


def test_the_retry_waits_the_backoff():
    waited: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    throttle = Throttle(
        min_interval=0.0, sleep=lambda s: waited.append(s), monotonic=lambda: 0.0
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = LichessExplorerClient("lip_x", UA, client=http, throttle=throttle)
    with pytest.raises(ExplorerRateLimited):
        client.masters(START_FEN)
    assert any(w >= 59 for w in waited), waited


def test_a_persistent_rate_limit_is_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with pytest.raises(ExplorerRateLimited, match="rate limiting"):
        client_for(handler).masters(START_FEN)


def test_retrying_can_be_disabled():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    with pytest.raises(ExplorerRateLimited):
        client_for(handler, retry_after_rate_limit=False).masters(START_FEN)
    assert calls["n"] == 1


def test_a_server_error_becomes_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(ExplorerUnavailable, match="HTTP 503"):
        client_for(handler).masters(START_FEN)


def test_a_404_is_reported_clearly():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(ExplorerUnavailable, match="does not know that position"):
        client_for(handler).masters(START_FEN)


def test_a_transport_failure_becomes_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(ExplorerUnavailable, match="Could not reach"):
        client_for(handler).masters(START_FEN)


def test_non_json_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    with pytest.raises(ExplorerUnavailable, match="non-JSON"):
        client_for(handler).masters(START_FEN)


def test_a_json_list_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2])

    with pytest.raises(ExplorerUnavailable, match="Unexpected response shape"):
        client_for(handler).masters(START_FEN)


def test_the_throttle_is_consulted_before_each_request():
    calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"white": 0, "draws": 0, "black": 0})

    throttle = Throttle(
        min_interval=1.0, sleep=lambda s: calls.append(s), monotonic=lambda: 0.0
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = LichessExplorerClient("lip_x", UA, client=http, throttle=throttle)
    client.masters(START_FEN)
    client.masters(START_FEN)
    assert calls == [1.0]


def test_an_injected_client_is_not_closed_by_us():
    http = httpx.Client(transport=httpx.MockTransport(ok()))
    client = LichessExplorerClient("lip_x", UA, client=http)
    client.close()
    assert not http.is_closed
    http.close()


def test_the_client_works_as_a_context_manager():
    with client_for(ok()) as client:
        assert client.masters(START_FEN)
