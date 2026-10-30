from __future__ import annotations

from chess_trainer.db import explorer_repo

EPD = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
PAYLOAD = {"white": 10, "draws": 5, "black": 2, "moves": [{"uci": "e2e4"}]}


def test_empty_cache(conn):
    assert explorer_repo.get(conn, EPD) is None
    assert not explorer_repo.has(conn, EPD)
    assert explorer_repo.total_games(conn, EPD) is None
    assert explorer_repo.count(conn) == 0


def test_put_then_get(conn):
    explorer_repo.put(conn, EPD, PAYLOAD, 17)
    assert explorer_repo.get(conn, EPD) == PAYLOAD
    assert explorer_repo.has(conn, EPD)


def test_the_total_is_stored_separately_for_queries(conn):
    explorer_repo.put(conn, EPD, PAYLOAD, 17)
    assert explorer_repo.total_games(conn, EPD) == 17


def test_putting_again_replaces(conn):
    explorer_repo.put(conn, EPD, PAYLOAD, 17)
    explorer_repo.put(conn, EPD, {"white": 1, "draws": 0, "black": 0}, 1)
    assert explorer_repo.count(conn) == 1
    assert explorer_repo.total_games(conn, EPD) == 1


def test_nested_structures_survive(conn):
    explorer_repo.put(conn, EPD, PAYLOAD, 17)
    assert explorer_repo.get(conn, EPD)["moves"][0]["uci"] == "e2e4"


def test_unicode_in_opening_names_survives(conn):
    payload = {"white": 1, "draws": 0, "black": 0, "opening": {"eco": "A00", "name": "Kádas Opening"}}
    explorer_repo.put(conn, EPD, payload, 1)
    assert explorer_repo.get(conn, EPD)["opening"]["name"] == "Kádas Opening"


def test_different_positions_are_separate(conn):
    other = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    explorer_repo.put(conn, EPD, PAYLOAD, 17)
    explorer_repo.put(conn, other, {"white": 1, "draws": 1, "black": 1}, 3)
    assert explorer_repo.count(conn) == 2
    assert explorer_repo.total_games(conn, other) == 3


def test_a_real_response_round_trips(conn, explorer_root):
    total = explorer_root["white"] + explorer_root["draws"] + explorer_root["black"]
    explorer_repo.put(conn, EPD, explorer_root, total)
    restored = explorer_repo.get(conn, EPD)
    assert len(restored["moves"]) == 20
    assert restored["moves"][0]["san"] == "e4"
