"""API fixtures: a TestClient with the engine and the Lichess explorer faked.

No test in this package touches the network or starts Stockfish.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from chess_trainer.api.app import create_app
from chess_trainer.api.deps import require_engine, require_explorer
from chess_trainer.config import Config
from tests.conftest import FakeEngine


@pytest.fixture
def fake_engine_for_api() -> FakeEngine:
    return FakeEngine()


class FakeExplorerClient:
    """A Lichess explorer backed by canned responses, keyed by EPD."""

    def __init__(self) -> None:
        self.by_epd: dict[str, dict] = {}
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.has_token = True

    def masters(self, fen: str, *, moves: int = 100) -> dict:
        import chess

        epd = chess.Board(fen).epd()
        self.calls.append(epd)
        if self.error is not None:
            raise self.error
        if epd not in self.by_epd:
            raise AssertionError(f"no canned explorer response for {epd}")
        return self.by_epd[epd]

    def load(self, ucis: list[str], payload: dict) -> None:
        """Register a response for the position reached by ``ucis``."""
        from chess_trainer.openings import line as line_module

        self.by_epd[line_module.position_of(ucis).epd] = payload

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def close(self) -> None:  # pragma: no cover - interface parity
        pass


@pytest.fixture
def fake_explorer() -> FakeExplorerClient:
    return FakeExplorerClient()


@pytest.fixture
def client(
    config: Config,
    fake_engine_for_api: FakeEngine,
    fake_explorer: FakeExplorerClient,
) -> Iterator[TestClient]:
    """A client whose engine and Lichess explorer are fakes."""
    app = create_app(config)
    app.dependency_overrides[require_engine] = lambda: fake_engine_for_api
    app.dependency_overrides[require_explorer] = lambda: fake_explorer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def real_client(config: Config) -> Iterator[TestClient]:
    """A client with no dependency overrides (the engine must really exist)."""
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client
