"""HTTP access to the public chess.com API.

The only module here that touches the network. It sends a descriptive
User-Agent, as chess.com asks, and maps HTTP failures onto exceptions the API
layer can turn into readable messages.

An ``httpx.Client`` can be injected, which is how the tests drive this against a
mock transport instead of the internet.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://api.chess.com/pub"
DEFAULT_TIMEOUT = 15.0


class ChessComError(RuntimeError):
    """Base class for chess.com API failures."""


class PlayerNotFound(ChessComError):
    """The username does not exist on chess.com."""


class ChessComRateLimited(ChessComError):
    """chess.com asked us to slow down."""


class ChessComUnavailable(ChessComError):
    """chess.com could not be reached, or returned an unusable response."""


class ChessComClient:
    """Reads one player's public game archives."""

    def __init__(
        self,
        username: str,
        user_agent: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.username = username.strip()
        self.user_agent = user_agent
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    # -- lifecycle -------------------------------------------------------
    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "ChessComClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- requests --------------------------------------------------------
    def _get(self, url: str) -> dict[str, Any]:
        try:
            response = self.client.get(
                url, headers={"User-Agent": self.user_agent}
            )
        except httpx.HTTPError as exc:
            raise ChessComUnavailable(f"Could not reach chess.com: {exc}") from exc

        if response.status_code == 404:
            raise PlayerNotFound(
                f"chess.com has no player called {self.username!r} "
                "(check CHESS_TRAINER_CHESSCOM_USERNAME)."
            )
        if response.status_code == 429:
            raise ChessComRateLimited(
                "chess.com is rate limiting us; wait a moment and try again."
            )
        if response.status_code >= 400:
            raise ChessComUnavailable(
                f"chess.com returned HTTP {response.status_code} for {url}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ChessComUnavailable(
                f"chess.com returned a non-JSON response for {url}"
            ) from exc
        if not isinstance(payload, dict):
            raise ChessComUnavailable(f"Unexpected response shape from {url}")
        return payload

    # -- endpoints -------------------------------------------------------
    def archive_urls(self) -> list[str]:
        """Every monthly archive URL for this player, as the API returns them."""
        payload = self._get(f"{self.base_url}/player/{self.username}/games/archives")
        archives = payload.get("archives")
        if not isinstance(archives, list):
            raise ChessComUnavailable("Archive list was missing from the response")
        return [url for url in archives if isinstance(url, str)]

    def archive_games(self, archive_url: str) -> list[dict[str, Any]]:
        """The raw game objects in one monthly archive (may be empty)."""
        payload = self._get(archive_url)
        games = payload.get("games")
        if games is None:
            return []
        if not isinstance(games, list):
            raise ChessComUnavailable(f"Unexpected 'games' shape from {archive_url}")
        return [game for game in games if isinstance(game, dict)]
