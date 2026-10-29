"""Command line entry point.

``chess-trainer`` (or ``python -m chess_trainer``) starts the local server and
opens the browser at it.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Sequence

from chess_trainer import __version__
from chess_trainer.config import Config, load_config

#: How long to wait for the server to accept connections before giving up on
#: opening a browser (the server itself keeps running regardless).
BROWSER_TIMEOUT_SECONDS = 15.0
BROWSER_POLL_SECONDS = 0.1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chess-trainer",
        description="Daily chess review and opening drills, served on localhost.",
    )
    parser.add_argument("--host", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Port to listen on (default: 8787)")
    parser.add_argument(
        "--depth", type=int, help="Stockfish search depth (default: 20)"
    )
    parser.add_argument("--stockfish", help="Path to the Stockfish binary")
    parser.add_argument("--db", help="Path to the SQLite database")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser",
    )
    parser.add_argument(
        "--version", action="version", version=f"chess-trainer {__version__}"
    )
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    """Environment config, with command line flags taking precedence."""
    from chess_trainer import paths

    config = load_config()
    return config.with_overrides(
        host=args.host,
        port=args.port,
        engine_depth=args.depth,
        stockfish_path=paths.expand(args.stockfish) if args.stockfish else None,
        db_path=paths.expand(args.db) if args.db else None,
        open_browser=False if args.no_browser else None,
    )


def wait_for_port(host: str, port: int, timeout: float = BROWSER_TIMEOUT_SECONDS) -> bool:
    """Block until the server accepts a TCP connection, or the timeout passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(BROWSER_POLL_SECONDS)
    return False


def open_browser_when_ready(config: Config) -> threading.Thread:
    """Open the browser once the server is listening, from a daemon thread."""

    def run() -> None:
        if wait_for_port(config.host, config.port):
            webbrowser.open(config.base_url)

    thread = threading.Thread(target=run, name="open-browser", daemon=True)
    thread.start()
    return thread


def serve(config: Config) -> None:
    import uvicorn

    from chess_trainer.api.app import create_app

    if config.open_browser:
        open_browser_when_ready(config)

    # flush=True so the banner shows immediately, including when stdout is a pipe.
    print(f"chess-trainer {__version__}  ->  {config.base_url}", flush=True)
    print(f"  database : {config.db_path}", flush=True)
    print(f"  engine   : {config.stockfish_path} (depth {config.engine_depth})", flush=True)
    print("  Press Ctrl+C to stop.\n", flush=True)

    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="info",
        access_log=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    try:
        serve(config)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nStopped.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
