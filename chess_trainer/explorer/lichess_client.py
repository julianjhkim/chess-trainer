"""HTTP access to the Lichess opening explorer.

The only module here that touches the network. The explorer requires a token
(the host returns 401 for every path without one), sent as a bearer token; a
descriptive User-Agent goes with it.

An ``httpx.Client`` can be injected, which is how the tests drive this against
a mock transport.
"""

from __future__ import annotations

from typing import Any

import httpx

from chess_trainer.explorer.rate_limit import (
    RATE_LIMIT_BACKOFF_SECONDS,
    Throttle,
)

BASE_URL = "https://explorer.lichess.ovh"
DEFAULT_TIMEOUT = 20.0

#: Ask for every continuation the database has, so the 5% branch filter sees
#: the complete move list rather than a truncated top-N.
MOVES_LIMIT = 100


class ExplorerError(RuntimeError):
    """Base class for explorer failures."""


class ExplorerTokenMissing(ExplorerError):
    """No Lichess token is configured."""


class ExplorerTokenRejected(ExplorerError):
    """The configured token was refused."""


class ExplorerRateLimited(ExplorerError):
    """Lichess asked us to slow down and we have already waited."""


class ExplorerUnavailable(ExplorerError):
    """The explorer could not be reached or returned something unusable."""


TOKEN_HELP = (
    "Create one at https://lichess.org/account/oauth/token/create "
    "(no scopes needed) and put it in .env as LICHESS_TOKEN=lip_..."
)


class LichessExplorerClient:
    """Reads positions from the masters database."""

    def __init__(
        self,
        token: str | None,
        user_agent: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
        base_url: str = BASE_URL,
        throttle: Throttle | None = None,
        retry_after_rate_limit: bool = True,
    ) -> None:
        self.token = token.strip() if token and token.strip() else None
        self.user_agent = user_agent
        self.base_url = base_url.rstrip("/")
        self.throttle = throttle or Throttle()
        self.retry_after_rate_limit = retry_after_rate_limit
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    # -- lifecycle -------------------------------------------------------
    @property
    def has_token(self) -> bool:
        return self.token is not None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, follow_redirects=True)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "LichessExplorerClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- requests --------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def masters(self, fen: str, *, moves: int = MOVES_LIMIT) -> dict[str, Any]:
        """Fetch the masters-database record for a position.

        On HTTP 429 this waits the 60 seconds the spec asks for and retries
        once; a second 429 is raised.
        """
        if not self.has_token:
            raise ExplorerTokenMissing(
                "The Lichess opening explorer needs an API token. " + TOKEN_HELP
            )

        params = {"fen": fen, "moves": str(moves), "topGames": "0"}
        url = f"{self.base_url}/masters"

        for attempt in (1, 2):
            self.throttle.wait()
            try:
                response = self.client.get(url, params=params, headers=self._headers())
            except httpx.HTTPError as exc:
                raise ExplorerUnavailable(
                    f"Could not reach the Lichess explorer: {exc}"
                ) from exc

            if response.status_code == 429:
                self.throttle.penalise(RATE_LIMIT_BACKOFF_SECONDS)
                if attempt == 1 and self.retry_after_rate_limit:
                    continue
                raise ExplorerRateLimited(
                    "Lichess is rate limiting the opening explorer. "
                    f"Waited {RATE_LIMIT_BACKOFF_SECONDS:.0f}s and it is still limited; "
                    "try again in a minute."
                )

            if response.status_code in (401, 403):
                raise ExplorerTokenRejected(
                    "Lichess rejected the API token (HTTP "
                    f"{response.status_code}). " + TOKEN_HELP
                )
            if response.status_code == 404:
                raise ExplorerUnavailable(
                    "The Lichess explorer does not know that position."
                )
            if response.status_code >= 400:
                raise ExplorerUnavailable(
                    f"The Lichess explorer returned HTTP {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise ExplorerUnavailable(
                    "The Lichess explorer returned a non-JSON response"
                ) from exc
            if not isinstance(payload, dict):
                raise ExplorerUnavailable(
                    "Unexpected response shape from the Lichess explorer"
                )
            return payload

        raise ExplorerRateLimited("Rate limited by the Lichess explorer")  # pragma: no cover
