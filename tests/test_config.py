from __future__ import annotations

from pathlib import Path

import pytest

from chess_trainer import config as config_module
from chess_trainer.config import Config, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove anything that would leak the developer's real settings in."""
    for key in list(dict(**__import__("os").environ)):
        if key.startswith(config_module.ENV_PREFIX) or key == "LICHESS_TOKEN":
            monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_spec():
    cfg = Config()
    assert cfg.chesscom_username == "test-player"
    assert cfg.engine_depth == 20
    assert cfg.host == "127.0.0.1"
    assert cfg.timezone == "Asia/Seoul"
    assert cfg.stockfish_path == Path("/opt/homebrew/bin/stockfish")


def test_db_path_defaults_when_omitted():
    assert Config().db_path is not None


def test_base_url_combines_host_and_port():
    assert Config(host="127.0.0.1", port=9000).base_url == "http://127.0.0.1:9000"


def test_user_agent_is_descriptive():
    assert "chess-trainer" in config_module.USER_AGENT
    assert "github.com" in config_module.USER_AGENT


def test_with_overrides_ignores_none():
    cfg = Config(port=1234)
    assert cfg.with_overrides(port=None).port == 1234
    assert cfg.with_overrides(port=4321).port == 4321


def test_load_config_reads_prefixed_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHESS_TRAINER_ENGINE_DEPTH", "12")
    monkeypatch.setenv("CHESS_TRAINER_PORT", "9999")
    monkeypatch.setenv("CHESS_TRAINER_CHESSCOM_USERNAME", "someone")
    cfg = load_config(env_file=tmp_path / "missing.env")
    assert (cfg.engine_depth, cfg.port, cfg.chesscom_username) == (12, 9999, "someone")


def test_load_config_accepts_bare_lichess_token(monkeypatch, tmp_path):
    monkeypatch.setenv("LICHESS_TOKEN", "lip_abc")
    assert load_config(env_file=tmp_path / "missing.env").lichess_token == "lip_abc"


def test_blank_token_becomes_none(monkeypatch, tmp_path):
    monkeypatch.setenv("LICHESS_TOKEN", "   ")
    assert load_config(env_file=tmp_path / "missing.env").lichess_token is None


def test_load_config_reads_env_file(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("LICHESS_TOKEN=lip_from_file\nCHESS_TRAINER_ENGINE_DEPTH=7\n")
    cfg = load_config(env_file=env)
    assert cfg.lichess_token == "lip_from_file"
    assert cfg.engine_depth == 7


def test_real_environment_beats_env_file(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("CHESS_TRAINER_ENGINE_DEPTH=7\n")
    monkeypatch.setenv("CHESS_TRAINER_ENGINE_DEPTH", "30")
    assert load_config(env_file=env).engine_depth == 30


def test_bad_integer_is_reported_clearly(monkeypatch, tmp_path):
    monkeypatch.setenv("CHESS_TRAINER_ENGINE_DEPTH", "deep")
    with pytest.raises(ValueError, match="must be an integer"):
        load_config(env_file=tmp_path / "missing.env")
