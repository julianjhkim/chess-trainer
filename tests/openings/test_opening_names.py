from __future__ import annotations

from chess_trainer.explorer.explorer_types import Opening, PositionStats
from chess_trainer.openings import opening_names


def test_the_position_opening_is_returned(explorer_e4):
    stats = PositionStats.of(explorer_e4)
    assert opening_names.of_position(stats).label == "B00 King's Pawn Game"


def test_the_root_has_no_opening(explorer_root):
    assert opening_names.of_position(PositionStats.of(explorer_root)) is None


def test_the_opening_after_a_move(explorer_e4):
    stats = PositionStats.of(explorer_e4)
    assert opening_names.after_move(stats, "c7c5").label == "B20 Sicilian Defense"
    assert opening_names.after_move(stats, "c7c6").label == "B10 Caro-Kann Defense"


def test_the_opening_after_an_unknown_move_is_none(explorer_e4):
    assert opening_names.after_move(PositionStats.of(explorer_e4), "h2h4") is None


def test_of_move_reads_the_move_entry(explorer_e4):
    stats = PositionStats.of(explorer_e4)
    assert opening_names.of_move(stats.by_games()[0]).eco == "B20"


def test_label_formats_eco_and_name():
    assert opening_names.label(Opening("C20", "King's Pawn Game")) == "C20 King's Pawn Game"


def test_label_of_nothing_is_none():
    assert opening_names.label(None) is None


def test_pick_takes_the_first_known_opening():
    sicilian = Opening("B20", "Sicilian")
    french = Opening("C00", "French")
    assert opening_names.pick(None, sicilian, french) is sicilian


def test_pick_of_all_unknown_is_none():
    assert opening_names.pick(None, None) is None


def test_names_come_from_the_explorer_not_from_us(explorer_root):
    """Every first move carries the explorer's own name."""
    stats = PositionStats.of(explorer_root)
    named = [opening_names.of_move(m) for m in stats.by_games()]
    assert all(n is not None for n in named)
    assert {n.name for n in named} >= {"King's Pawn Game", "English Opening"}
