from __future__ import annotations

from chess_trainer.db import explorer_repo
from chess_trainer.explorer import cache

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
START_EPD = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"


class FakeSource:
    def __init__(self, payload=None):
        self.payload = payload or {"white": 10, "draws": 5, "black": 2, "moves": []}
        self.calls: list[str] = []

    def masters(self, fen: str, *, moves: int = 100) -> dict:
        self.calls.append(fen)
        return self.payload


def test_the_first_fetch_goes_to_the_source(conn):
    source = FakeSource()
    payload = cache.fetch(conn, source, fen=START_FEN, epd=START_EPD)
    assert payload == source.payload
    assert source.calls == [START_FEN]


def test_the_result_is_cached(conn):
    source = FakeSource()
    cache.fetch(conn, source, fen=START_FEN, epd=START_EPD)
    assert explorer_repo.get(conn, START_EPD) == source.payload


def test_the_second_fetch_is_served_from_the_cache(conn):
    source = FakeSource()
    cache.fetch(conn, source, fen=START_FEN, epd=START_EPD)
    cache.fetch(conn, source, fen=START_FEN, epd=START_EPD)
    assert len(source.calls) == 1


def test_the_total_is_stored_alongside(conn):
    cache.fetch(conn, FakeSource(), fen=START_FEN, epd=START_EPD)
    assert explorer_repo.total_games(conn, START_EPD) == 17


def test_use_cache_false_forces_a_refetch(conn):
    source = FakeSource()
    cache.fetch(conn, source, fen=START_FEN, epd=START_EPD)
    cache.fetch(conn, source, fen=START_FEN, epd=START_EPD, use_cache=False)
    assert len(source.calls) == 2


def test_cached_only_never_calls_the_source(conn):
    source = FakeSource()
    assert cache.cached_only(conn, START_EPD) is None
    cache.fetch(conn, source, fen=START_FEN, epd=START_EPD)
    assert cache.cached_only(conn, START_EPD) is not None
    assert len(source.calls) == 1


def test_transposing_fens_share_one_cache_entry(conn):
    """The explorer is position-based, so the EPD is the key.

    Two move orders reaching the same position differ only in the FEN's
    halfmove counter; caching by EPD means the second one is free.
    """
    source = FakeSource()
    epd = "rnbqkbnr/ppp1pppp/8/3p4/3P4/5N2/PPP1PPPP/RNBQKB1R b KQkq -"
    cache.fetch(conn, source, fen=f"{epd} 0 2", epd=epd)
    cache.fetch(conn, source, fen=f"{epd} 1 2", epd=epd)
    assert len(source.calls) == 1
    assert explorer_repo.count(conn) == 1


def test_a_corrupted_cache_row_is_ignored(conn):
    from chess_trainer.db.connection import transaction

    with transaction(conn):
        conn.execute(
            "INSERT INTO explorer_cache (epd, response, total_games, fetched_at)"
            " VALUES (?, 'not json', 0, 'now')",
            (START_EPD,),
        )
    assert explorer_repo.get(conn, START_EPD) is None


def test_a_real_response_round_trips(conn, explorer_e4):
    class Source:
        def masters(self, fen, *, moves=100):
            return explorer_e4

    cache.fetch(conn, Source(), fen=START_FEN, epd=START_EPD)
    restored = explorer_repo.get(conn, START_EPD)
    assert restored["moves"][0]["san"] == "c5"
    assert explorer_repo.total_games(conn, START_EPD) == 1309466
