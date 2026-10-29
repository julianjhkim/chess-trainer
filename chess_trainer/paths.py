"""Filesystem locations used by the app.

Kept separate from :mod:`chess_trainer.config` so that path resolution can be
tested without touching the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "chess-trainer"
DB_FILE_NAME = "chess_trainer.db"


def default_data_dir() -> Path:
    """Where the SQLite database and other local state live."""
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME


def default_db_path() -> Path:
    return default_data_dir() / DB_FILE_NAME


def expand(path: str | os.PathLike[str]) -> Path:
    """Expand ``~`` and environment variables, returning an absolute path."""
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


def find_frontend_dir(start: Path | None = None) -> Path:
    """Locate the ``frontend/`` directory.

    The frontend is not packaged inside ``chess_trainer``, so walk up from this
    file looking for a directory that contains ``frontend/index.html``.
    """
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        frontend = candidate / "frontend"
        if (frontend / "index.html").is_file():
            return frontend
    raise FileNotFoundError(
        "Could not locate frontend/index.html; expected it alongside the "
        "chess_trainer package."
    )


def ensure_parent(path: Path) -> Path:
    """Create the parent directory of ``path`` if needed, then return ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
