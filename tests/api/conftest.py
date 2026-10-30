"""API fixtures: a TestClient with the engine and chess.com both faked.

No test in this package touches the network or starts Stockfish.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from chess_trainer.api.app import create_app
from chess_trainer.api.deps import get_chesscom, require_engine
from chess_trainer.config import Config
from tests.conftest import FakeEngine


@pytest.fixture
def fake_engine_for_api() -> FakeEngine:
    return FakeEngine()


class FakeChessCom:
    """A chess.com client backed by canned archives, with call counting."""

    def __init__(self) -> None:
        self.username = "test-player"
        self.archives: dict[str, list[dict]] = {}
        self.error: Exception | None = None
        self.calls = 0

    def set_games(self, games: list[dict], month: str = "2026/10") -> None:
        url = f"https://api.chess.com/pub/player/test-player/games/{month}"
        self.archives = {url: games}

    def archive_urls(self) -> list[str]:
        if self.error is not None:
            raise self.error
        return list(self.archives)

    def archive_games(self, archive_url: str) -> list[dict]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.archives.get(archive_url, [])

    def close(self) -> None:  # pragma: no cover - interface parity
        pass


@pytest.fixture
def fake_chesscom() -> FakeChessCom:
    return FakeChessCom()


@pytest.fixture
def client(
    config: Config, fake_engine_for_api: FakeEngine, fake_chesscom: FakeChessCom
) -> Iterator[TestClient]:
    """A client for an app backed by a temp database, fake engine and fake API."""
    app = create_app(config)
    app.dependency_overrides[require_engine] = lambda: fake_engine_for_api
    app.dependency_overrides[get_chesscom] = lambda: fake_chesscom
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def real_client(config: Config) -> Iterator[TestClient]:
    """A client with no dependency overrides (the engine must really exist)."""
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client
