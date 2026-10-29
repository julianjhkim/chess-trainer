from __future__ import annotations

from chess_trainer.db import schema
from chess_trainer.db.connection import connect


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "chess-trainer" in response.text


def test_frontend_modules_are_served(client):
    assert client.get("/js/app.js").status_code == 200
    assert client.get("/css/app.css").status_code == 200


def test_chessground_is_vendored_locally(client):
    """The app must work offline, so chessground is served from the repo."""
    response = client.get("/vendor/chessground/chessground.js")
    assert response.status_code == 200
    assert "Chessground" in response.text


def test_chessground_styles_are_vendored(client):
    for sheet in ("base", "brown", "cburnett"):
        assert client.get(f"/vendor/chessground/chessground.{sheet}.css").status_code == 200


def test_the_page_references_no_external_hosts(client):
    """No CDN at runtime: every src/href in the page must be local."""
    import re

    html = client.get("/").text
    urls = re.findall(r'(?:src|href)="([^"]+)"', html)
    external = [u for u in urls if u.startswith(("http://", "https://", "//"))]
    assert external == []


def test_lifespan_migrates_the_database(config):
    from fastapi.testclient import TestClient

    from chess_trainer.api.app import create_app

    config.db_path.unlink()
    with TestClient(create_app(config)) as client:
        assert client.get("/api/health").status_code == 200

    conn = connect(config.db_path)
    assert schema.current_version(conn) == schema.latest_version()
    conn.close()


def test_unknown_paths_404(client):
    assert client.get("/no/such/page").status_code == 404
