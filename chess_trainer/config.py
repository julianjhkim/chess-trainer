"""Application settings, read from the environment (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

from chess_trainer import __version__, paths

ENV_PREFIX = "CHESS_TRAINER_"

DEFAULT_USERNAME = "test-player"
DEFAULT_STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
DEFAULT_DEPTH = 20
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_TIMEZONE = "Asia/Seoul"

#: Descriptive User-Agent, as the chess.com and Lichess APIs both ask for.
USER_AGENT = (
    f"chess-trainer/{__version__} "
    "(local personal training tool; +https://github.com/julianjhkim/chess-trainer)"
)


@dataclass(frozen=True, slots=True)
class Config:
    chesscom_username: str = DEFAULT_USERNAME
    stockfish_path: Path = Path(DEFAULT_STOCKFISH_PATH)
    engine_depth: int = DEFAULT_DEPTH
    lichess_token: str | None = None
    db_path: Path = None  # type: ignore[assignment]  # filled in __post_init__
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timezone: str = DEFAULT_TIMEZONE
    user_agent: str = USER_AGENT
    open_browser: bool = True

    def __post_init__(self) -> None:
        if self.db_path is None:
            object.__setattr__(self, "db_path", paths.default_db_path())

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def with_overrides(self, **kwargs: object) -> "Config":
        """Return a copy with the non-``None`` keyword arguments applied."""
        given = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **given)  # type: ignore[arg-type]


def _env(name: str, default: str | None = None) -> str | None:
    """Read ``CHESS_TRAINER_<NAME>``, falling back to bare ``<NAME>``."""
    return os.environ.get(ENV_PREFIX + name) or os.environ.get(name) or default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{ENV_PREFIX}{name} must be an integer, got {raw!r}"
        ) from exc


def load_config(env_file: Path | None = None) -> Config:
    """Build a :class:`Config` from the environment, loading ``.env`` first.

    Values already present in the real environment win over the ``.env`` file.
    """
    if env_file is None:
        try:
            env_file = paths.find_frontend_dir().parent / ".env"
        except FileNotFoundError:
            env_file = Path.cwd() / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)

    db_raw = _env("DB")
    token = _env("LICHESS_TOKEN")
    return Config(
        chesscom_username=_env("CHESSCOM_USERNAME", DEFAULT_USERNAME) or DEFAULT_USERNAME,
        stockfish_path=paths.expand(
            _env("STOCKFISH_PATH", DEFAULT_STOCKFISH_PATH) or DEFAULT_STOCKFISH_PATH
        ),
        engine_depth=_env_int("ENGINE_DEPTH", DEFAULT_DEPTH),
        lichess_token=token.strip() if token and token.strip() else None,
        db_path=paths.expand(db_raw) if db_raw else paths.default_db_path(),
        host=_env("HOST", DEFAULT_HOST) or DEFAULT_HOST,
        port=_env_int("PORT", DEFAULT_PORT),
        timezone=_env("TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE,
    )
