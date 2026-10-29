from __future__ import annotations

import socket
import threading

import pytest

from chess_trainer.cli import build_parser, config_from_args, wait_for_port


def parse(*argv):
    return build_parser().parse_args(list(argv))


def test_parser_defaults_to_nothing_set():
    args = parse()
    assert args.host is None and args.port is None and args.depth is None
    assert args.no_browser is False


def test_parser_reads_flags():
    args = parse("--host", "0.0.0.0", "--port", "9000", "--depth", "12", "--no-browser")
    assert (args.host, args.port, args.depth, args.no_browser) == (
        "0.0.0.0",
        9000,
        12,
        True,
    )


def test_version_flag_exits():
    with pytest.raises(SystemExit) as exc:
        parse("--version")
    assert exc.value.code == 0


def test_invalid_port_is_rejected():
    with pytest.raises(SystemExit):
        parse("--port", "not-a-number")


def test_config_from_args_applies_overrides(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = config_from_args(parse("--port", "9123", "--depth", "7"))
    assert config.port == 9123
    assert config.engine_depth == 7


def test_config_from_args_leaves_defaults_alone(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert config_from_args(parse()).port == 8787


def test_no_browser_disables_opening(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert config_from_args(parse("--no-browser")).open_browser is False
    assert config_from_args(parse()).open_browser is True


def test_stockfish_and_db_paths_are_expanded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = config_from_args(parse("--stockfish", "~/sf", "--db", "~/x.db"))
    assert config.stockfish_path.is_absolute()
    assert config.db_path.is_absolute()


def test_wait_for_port_detects_a_listening_socket():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    threading.Thread(target=lambda: None, daemon=True).start()
    try:
        assert wait_for_port("127.0.0.1", port, timeout=2.0)
    finally:
        server.close()


def test_wait_for_port_times_out_on_a_closed_port():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.close()
    assert not wait_for_port("127.0.0.1", port, timeout=0.5)
