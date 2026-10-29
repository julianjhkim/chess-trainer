from __future__ import annotations

from pathlib import Path

from chess_trainer import paths


def test_default_data_dir_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.default_data_dir() == tmp_path / paths.APP_DIR_NAME


def test_default_data_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    expected = Path.home() / ".local" / "share" / paths.APP_DIR_NAME
    assert paths.default_data_dir() == expected


def test_default_db_path_sits_in_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.default_db_path().name == paths.DB_FILE_NAME
    assert paths.default_db_path().parent == paths.default_data_dir()


def test_expand_handles_tilde_and_vars(monkeypatch):
    monkeypatch.setenv("CT_TEST_DIR", "sub")
    result = paths.expand("~/$CT_TEST_DIR/file.db")
    assert result.is_absolute()
    assert result.parts[-2:] == ("sub", "file.db")
    assert str(result).startswith(str(Path.home()))


def test_find_frontend_dir_locates_real_frontend():
    frontend = paths.find_frontend_dir()
    assert (frontend / "index.html").is_file()
    assert (frontend / "js" / "app.js").is_file()


def test_find_frontend_dir_raises_when_absent(tmp_path):
    try:
        paths.find_frontend_dir(start=tmp_path / "nowhere" / "x.py")
    except FileNotFoundError as exc:
        assert "frontend/index.html" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_ensure_parent_creates_directory(tmp_path):
    target = tmp_path / "a" / "b" / "db.sqlite"
    assert paths.ensure_parent(target) == target
    assert target.parent.is_dir()
