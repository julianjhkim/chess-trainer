"""My moves: main line only; the opponent's: every reply the rules allow."""

from __future__ import annotations

import copy

import pytest

from chess_trainer.db import cards_repo
from chess_trainer.openings import card_builder, line as line_module, repertoire
from tests.conftest import explorer_record
from tests.openings.test_card_builder import FakeExplorer, epd_of


def test_my_white_first_moves_are_studied_from_both_sides():
    for first in ("e2e4", "d2d4", "g1f3", "c2c4"):
        assert not repertoire.black_only([first, "e7e5"])


def test_any_other_first_move_is_black_only():
    assert repertoire.black_only(["g2g3"])
    assert repertoire.black_only(["b2b3", "e7e5", "c1b2"])
    assert not repertoire.black_only([])


#: White's replies after 1.g3 c5: four at 5%+, a 1,000-game sideline (2.b3,
#: a first reply, so it counts) and a rare one (2.h4).
G3_C5 = explorer_record(
    {"e2e4": 40000, "d2d4": 30000, "g1f3": 9000, "c2c4": 6000, "b2b3": 1200, "h2h4": 300}
)


@pytest.fixture
def explorer(explorer_root, explorer_e4) -> FakeExplorer:
    """1.g3 answered by 1...c5 (the e4 record's shape: Black's moves), then
    White's replies from the root record's shape: e4, d4, Nf3 and c4 at 5%+."""
    return FakeExplorer(
        {
            epd_of([]): explorer_root,
            epd_of(["g2g3"]): explorer_e4,
            epd_of(["g2g3", "c7c5"]): G3_C5,
        }
    )


def g3_card(conn, explorer, engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.get_by_epd(conn, epd_of(["g2g3"]))
    return card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10).card


def test_a_black_only_card_branches_only_through_its_answer(conn, explorer, fake_engine):
    card = g3_card(conn, explorer, fake_engine)
    assert card.answer_uci == "c7c5"
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    lines = [c.line_uci for c in result.new_cards]
    assert lines == [
        "g2g3 c7c5 e2e4", "g2g3 c7c5 d2d4", "g2g3 c7c5 g1f3", "g2g3 c7c5 c2c4",
        "g2g3 c7c5 b2b3",
    ]


def test_no_card_asks_whites_move_in_a_black_only_line(conn, explorer, fake_engine):
    card = g3_card(conn, explorer, fake_engine)
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert cards_repo.get_by_epd(conn, epd_of(["g2g3", "c7c5"])) is None
    assert cards_repo.get_by_epd(conn, epd_of(["g2g3", "e7e5"])) is None
    assert all(c.side_to_move == "black" for c in result.new_cards)
    assert all(c.parent_card_id == card.id for c in result.new_cards)
    assert all(c.depth == 3 for c in result.new_cards)


def test_the_arrow_is_whites_reply_after_the_answer_replays(conn, explorer, fake_engine):
    card = g3_card(conn, explorer, fake_engine)
    child = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    ).new_cards[0]
    assert child.given_move_san == "e4"
    assert child.ucis[:-1] == ("g2g3", "c7c5")


def test_replies_the_record_does_not_name_keep_the_cards_name(conn, explorer, fake_engine):
    card = g3_card(conn, explorer, fake_engine)
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    # The g3 card took the e4 record's name; the c5 move's own name comes next.
    assert result.new_cards[0].opening_label == "B20 Sicilian Defense"


def test_the_arrow_is_played_from_the_position_after_the_answer(conn, explorer, fake_engine):
    card = g3_card(conn, explorer, fake_engine)
    child = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    ).new_cards[0]
    assert card_builder.opening_before(conn, child) == "B20 Sicilian Defense"


def test_my_white_first_moves_also_root_my_white_side(conn, explorer, explorer_e4, fake_engine):
    explorer.by_epd[epd_of(["e2e4"])] = explorer_e4
    explorer.by_epd[epd_of(["e2e4", "c7c5"])] = explorer_record({"g1f3": 700})
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.get_by_epd(conn, epd_of(["e2e4"]))
    card = card_builder.prepare_card(conn, explorer, fake_engine, card, engine_depth=10).card
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    lines = [c.line_uci for c in result.new_cards]
    assert lines[:4] == ["e2e4 c7c5", "e2e4 e7e5", "e2e4 e7e6", "e2e4 c7c6"]
    assert lines[-1] == "e2e4 c7c5 g1f3"  # my Black move next
    assert all(c.side_to_move == "white" for c in result.new_cards[:-1])


def test_a_black_only_first_move_roots_no_white_side(conn, explorer, fake_engine):
    card = g3_card(conn, explorer, fake_engine)
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert all(c.depth == 3 for c in result.new_cards)


def test_too_few_games_after_the_answer_is_a_dead_end(conn, explorer, explorer_thin, fake_engine):
    thin = copy.deepcopy(explorer_thin)
    thin["white"], thin["draws"], thin["black"] = 2, 1, 1
    thin["moves"] = []
    explorer.by_epd[epd_of(["g2g3", "c7c5"])] = thin
    card = g3_card(conn, explorer, fake_engine)
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert result.new_cards == []
    assert [c.line_uci for c in result.dead_ends] == ["g2g3 c7c5"]
    assert result.dead_ends[0].position_games == 4


def test_a_thin_position_after_the_answer_branches_on_the_engines_reply(
    conn, explorer, explorer_thin, fake_engine
):
    explorer.by_epd[epd_of(["g2g3", "c7c5"])] = explorer_thin  # 11 games
    fake_engine.best_moves[line_module.position_of(["g2g3", "c7c5"]).fen] = "f1g2"
    card = g3_card(conn, explorer, fake_engine)
    result = card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    rows = result.new_cards + result.dead_ends
    assert [c.line_uci for c in rows] == ["g2g3 c7c5 f1g2"]


def test_older_first_move_cards_are_widened_from_cached_records(
    conn, explorer, explorer_e4, fake_engine
):
    """A first-move card grown before the 1,000-game rule gets its sidelines."""
    explorer.by_epd[epd_of(["e2e4"])] = explorer_e4
    explorer.by_epd[epd_of(["e2e4", "c7c5"])] = explorer_record(
        {"g1f3": 9000, "b1c3": 800, "c2c4": 1100}
    )
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.get_by_epd(conn, epd_of(["e2e4"]))
    card = card_builder.prepare_card(conn, explorer, fake_engine, card, engine_depth=10).card
    card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    # Undo the wide part, as an older tree would have it.
    for line in (["e2e4", "b7b6"], ["e2e4", "c7c5", "c2c4"]):
        cards_repo.delete(conn, cards_repo.get_by_epd(conn, epd_of(line)).id)
    calls = explorer.call_count

    assert card_builder.widen_first_replies(conn) == 2
    assert cards_repo.get_by_epd(conn, epd_of(["e2e4", "b7b6"])) is not None
    assert cards_repo.get_by_epd(conn, epd_of(["e2e4", "c7c5", "c2c4"])) is not None
    assert explorer.call_count == calls  # cached records only
    assert card_builder.widen_first_replies(conn) == 0
