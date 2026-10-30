from __future__ import annotations

from chess_trainer.explorer.explorer_types import PositionStats
from chess_trainer.openings import stats_table
from chess_trainer.openings.card_types import CardMode


def stats(moves: list[tuple[str, int, int, int]], total: int | None = None):
    """Moves as (uci, white, draws, black)."""
    games = sum(w + d + b for _, w, d, b in moves) if total is None else total
    return PositionStats.of(
        {
            "white": games,
            "draws": 0,
            "black": 0,
            "moves": [
                {
                    "uci": uci,
                    "san": uci,
                    "white": w,
                    "draws": d,
                    "black": b,
                    "averageRating": 2400,
                }
                for uci, w, d, b in moves
            ],
        }
    )


def test_one_row_per_move():
    table = stats_table.build(
        stats([("a", 10, 0, 0), ("b", 5, 0, 0)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert [r.san for r in table.rows] == ["a", "b"]


def test_rows_are_most_played_first():
    table = stats_table.build(
        stats([("a", 1, 0, 0), ("b", 10, 0, 0)]), answer_uci="b", mode=CardMode.FREQUENCY
    )
    assert [r.san for r in table.rows] == ["b", "a"]


def test_the_answer_is_flagged():
    table = stats_table.build(
        stats([("a", 10, 0, 0), ("b", 5, 0, 0)]), answer_uci="b", mode=CardMode.FREQUENCY
    )
    assert [r.san for r in table.rows if r.is_answer] == ["b"]


def test_shares_and_counts():
    table = stats_table.build(
        stats([("a", 75, 0, 0), ("b", 25, 0, 0)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert table.total_games == 100
    assert table.rows[0].share == 75.0
    assert table.rows[0].games == 75


def test_the_white_draw_black_split():
    table = stats_table.build(
        stats([("a", 50, 30, 20)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    row = table.rows[0]
    assert (row.white, row.draws, row.black) == (50, 30, 20)
    assert row.white_percent == 50.0
    assert row.draw_percent == 30.0
    assert row.black_percent == 20.0


def test_percentages_of_an_empty_row_are_zero():
    table = stats_table.build(
        stats([("a", 0, 0, 0)], total=10), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert table.rows[0].white_percent == 0.0


def test_the_average_rating_is_carried():
    table = stats_table.build(
        stats([("a", 10, 0, 0)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert table.rows[0].average_rating == 2400


# -- engine mode ---------------------------------------------------------
def test_the_engine_move_is_marked_in_engine_mode():
    table = stats_table.build(
        stats([("a", 7, 0, 0), ("b", 3, 0, 0)]),
        answer_uci="b",
        mode=CardMode.ENGINE,
        engine_move_uci="b",
    )
    assert [r.san for r in table.rows if r.is_engine_move] == ["b"]


def test_nothing_is_marked_as_the_engine_move_in_frequency_mode():
    table = stats_table.build(
        stats([("a", 10, 0, 0)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert not any(r.is_engine_move for r in table.rows)


def test_an_engine_move_absent_from_the_database_gets_a_row():
    table = stats_table.build(
        stats([("a", 7, 0, 0)]),
        answer_uci="h2h4",
        mode=CardMode.ENGINE,
        engine_move_uci="h2h4",
    )
    added = [r for r in table.rows if r.uci == "h2h4"]
    assert added and added[0].games == 0
    assert added[0].is_answer and added[0].is_engine_move


def test_the_engine_note_explains_why():
    table = stats_table.build(
        stats([("a", 7, 0, 0)], total=11), answer_uci="a", mode=CardMode.ENGINE
    )
    assert "11 master games" in table.engine_note
    assert "Stockfish decides" in table.engine_note


def test_there_is_no_engine_note_in_frequency_mode():
    table = stats_table.build(
        stats([("a", 100, 0, 0)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert table.engine_note is None


# -- ties ----------------------------------------------------------------
def test_tied_moves_are_flagged_and_noted():
    table = stats_table.build(
        stats([("a", 10, 0, 0), ("b", 10, 0, 0), ("c", 1, 0, 0)]),
        answer_uci="a",
        mode=CardMode.FREQUENCY,
        tied_ucis=("a", "b"),
    )
    assert {r.san for r in table.rows if r.is_tied} == {"a", "b"}
    assert "played equally often" in table.tie_note
    assert "Stockfish picked" in table.tie_note


def test_a_single_tied_move_is_not_a_tie():
    table = stats_table.build(
        stats([("a", 10, 0, 0)]),
        answer_uci="a",
        mode=CardMode.FREQUENCY,
        tied_ucis=("a",),
    )
    assert table.tie_note is None


def test_no_tie_note_without_ties():
    table = stats_table.build(
        stats([("a", 10, 0, 0)]), answer_uci="a", mode=CardMode.FREQUENCY
    )
    assert table.tie_note is None


# -- edges ---------------------------------------------------------------
def test_an_empty_position_makes_an_empty_table():
    table = stats_table.build(stats([]), answer_uci=None, mode=None)
    assert table.is_empty
    assert table.rows == []


def test_the_real_e4_table(explorer_e4):
    table = stats_table.build(
        PositionStats.of(explorer_e4), answer_uci="c7c5", mode=CardMode.FREQUENCY
    )
    assert table.total_games == 1309466
    assert table.rows[0].san == "c5"
    assert table.rows[0].is_answer
    assert len(table.rows) == 19
    assert 45 < table.rows[0].share < 47
    assert table.rows[0].average_rating == 2401
