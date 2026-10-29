"""API fixtures: a TestClient whose engine dependency is a fake."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from chess_trainer.api.app import create_app
from chess_trainer.api.deps import require_engine
from chess_trainer.config import Config
from tests.conftest import FakeEngine


@pytest.fixture
def fake_engine_for_api() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def client(config: Config, fake_engine_for_api: FakeEngine) -> Iterator[TestClient]:
    """A client for an app backed by a temp database and a fake engine."""
    app = create_app(config)
    app.dependency_overrides[require_engine] = lambda: fake_engine_for_api
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def real_client(config: Config) -> Iterator[TestClient]:
    """A client with no dependency overrides (the engine must really exist)."""
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client
