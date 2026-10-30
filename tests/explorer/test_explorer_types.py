from __future__ import annotations

from chess_trainer.explorer.explorer_types import MoveStat, Opening, PositionStats


def move(uci="e2e4", san="e4", white=10, draws=20, black=5, rating=2400, opening=None):
    return {
        "uci": uci,
        "san": san,
        "white": white,
        "draws": draws,
        "black": black,
        "averageRating": rating,
        "opening": opening,
    }


# -- Opening -------------------------------------------------------------
def test_opening_label_joins_eco_and_name():
    assert Opening(eco="B20", name="Sicilian Defense").label == "B20 Sicilian Defense"


def test_opening_of_a_payload():
    assert Opening.of({"eco": "B20", "name": "Sicilian"}) == Opening("B20", "Sicilian")


def test_opening_of_nothing_is_none():
    assert Opening.of(None) is None
    assert Opening.of("not a dict") is None
    assert Opening.of({}) is None
    assert Opening.of({"eco": "B20"}) is None


# -- MoveStat ------------------------------------------------------------
def test_games_is_the_sum_of_results():
    assert MoveStat.of(move(white=10, draws=20, black=5)).games == 35


def test_share_of_a_total():
    assert MoveStat.of(move(white=50, draws=0, black=0)).share_of(200) == 25.0


def test_share_of_zero_total_is_zero():
    assert MoveStat.of(move()).share_of(0) == 0.0


def test_move_keeps_san_and_rating():
    stat = MoveStat.of(move(san="Nf3", rating=2418))
    assert stat.san == "Nf3"
    assert stat.average_rating == 2418


def test_san_falls_back_to_uci():
    assert MoveStat.of({"uci": "e2e4"}).san == "e2e4"


def test_missing_counts_default_to_zero():
    assert MoveStat.of({"uci": "e2e4"}).games == 0


def test_non_numeric_rating_becomes_none():
    assert MoveStat.of(move(rating="high")).average_rating is None


def test_move_carries_the_opening_after_it():
    stat = MoveStat.of(move(opening={"eco": "B20", "name": "Sicilian"}))
    assert stat.opening.eco == "B20"


# -- PositionStats -------------------------------------------------------
def test_total_games_sums_the_position_results():
    stats = PositionStats.of({"white": 100, "draws": 50, "black": 25, "moves": []})
    assert stats.total_games == 175


def test_empty_position():
    stats = PositionStats.of({})
    assert stats.total_games == 0
    assert stats.is_empty
    assert stats.moves == []


def test_by_games_orders_most_played_first():
    stats = PositionStats.of(
        {
            "white": 0,
            "draws": 0,
            "black": 0,
            "moves": [
                move("a2a3", "a3", white=1, draws=0, black=0),
                move("e2e4", "e4", white=100, draws=0, black=0),
                move("d2d4", "d4", white=50, draws=0, black=0),
            ],
        }
    )
    assert [m.san for m in stats.by_games()] == ["e4", "d4", "a3"]


def test_by_games_breaks_ties_by_uci_for_determinism():
    stats = PositionStats.of(
        {
            "moves": [
                move("e2e4", "e4", white=10, draws=0, black=0),
                move("d2d4", "d4", white=10, draws=0, black=0),
            ]
        }
    )
    assert [m.uci for m in stats.by_games()] == ["d2d4", "e2e4"]


def test_move_lookup():
    stats = PositionStats.of({"moves": [move("e2e4", "e4")]})
    assert stats.move("e2e4").san == "e4"
    assert stats.move("d2d4") is None


def test_malformed_moves_are_dropped():
    stats = PositionStats.of({"moves": [move(), {"no_uci": True}, "junk"]})
    assert len(stats.moves) == 1


def test_a_non_list_moves_field_is_ignored():
    assert PositionStats.of({"moves": "nope"}).moves == []


def test_position_opening_is_parsed():
    stats = PositionStats.of({"opening": {"eco": "B20", "name": "Sicilian"}})
    assert stats.opening.label == "B20 Sicilian"


def test_the_real_root_response(explorer_root):
    stats = PositionStats.of(explorer_root)
    assert stats.total_games > 2_000_000
    assert stats.opening is None  # the start position has no opening
    assert [m.san for m in stats.by_games()[:4]] == ["e4", "d4", "Nf3", "c4"]


def test_the_real_e4_response(explorer_e4):
    stats = PositionStats.of(explorer_e4)
    assert stats.opening.label == "B00 King's Pawn Game"
    best = stats.by_games()[0]
    assert best.san == "c5"
    assert best.opening.label == "B20 Sicilian Defense"
    assert 45 < best.share_of(stats.total_games) < 47
