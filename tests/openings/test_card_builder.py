"""Lazy tree growth, driven by canned explorer responses and a fake engine."""

from __future__ import annotations

import pytest

from chess_trainer.db import cards_repo, explorer_repo
from chess_trainer.openings import card_builder, line as line_module
from chess_trainer.openings.card_types import CardMode
from tests.conftest import FakeEngine


class FakeExplorer:
    """Serves canned responses by EPD and counts requests."""

    def __init__(self, by_epd: dict[str, dict]) -> None:
        self.by_epd = by_epd
        self.calls: list[str] = []

    def masters(self, fen: str, *, moves: int = 100) -> dict:
        import chess

        epd = chess.Board(fen).epd()
        self.calls.append(epd)
        if epd not in self.by_epd:
            raise AssertionError(f"no canned response for {epd}")
        return self.by_epd[epd]

    @property
    def call_count(self) -> int:
        return len(self.calls)


def epd_of(ucis: list[str]) -> str:
    return line_module.position_of(ucis).epd


@pytest.fixture
def explorer(explorer_root, explorer_e4, explorer_deep, explorer_thin) -> FakeExplorer:
    deep_line = [
        "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6",
        "e1g1", "f6e4", "d2d4", "e4d6", "b5c6", "d7c6",
        "d4e5", "d6f5",
    ]
    return FakeExplorer(
        {
            epd_of([]): explorer_root,
            epd_of(["e2e4"]): explorer_e4,
            epd_of(deep_line): explorer_deep,
            epd_of([*deep_line, "h2h3"]): explorer_thin,
        }
    )


# -- bootstrap -----------------------------------------------------------
def test_bootstrap_creates_one_card_per_first_move(conn, explorer):
    created = card_builder.ensure_bootstrapped(conn, explorer)
    assert len(created) == 20
    assert all(c.depth == 1 for c in created)


def test_bootstrap_costs_one_request(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    assert explorer.call_count == 1


def test_bootstrap_orders_by_game_count(conn, explorer):
    created = card_builder.ensure_bootstrapped(conn, explorer)
    assert [c.given_move_san for c in created[:4]] == ["e4", "d4", "Nf3", "c4"]
    counts = [c.position_games for c in created]
    assert counts == sorted(counts, reverse=True)


def test_bootstrap_applies_no_share_filter(conn, explorer):
    """The root is the exception: even 12-game first moves get a card."""
    created = card_builder.ensure_bootstrapped(conn, explorer)
    assert min(c.position_games for c in created) < 20


def test_bootstrap_records_the_opening_of_each_first_move(conn, explorer):
    created = card_builder.ensure_bootstrapped(conn, explorer)
    by_move = {c.given_move_san: c for c in created}
    assert by_move["e4"].opening_label == "B00 King's Pawn Game"
    assert by_move["c4"].opening_name == "English Opening"


def test_bootstrap_sets_the_side_to_move_to_black(conn, explorer):
    created = card_builder.ensure_bootstrapped(conn, explorer)
    assert all(c.side_to_move == "black" for c in created)


def test_bootstrap_does_not_create_the_root_itself(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    assert cards_repo.get_by_epd(conn, epd_of([])) is None


def test_bootstrap_is_idempotent(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    assert card_builder.ensure_bootstrapped(conn, explorer) == []
    assert cards_repo.count(conn) == 20


def test_bootstrap_leaves_answers_unresolved(conn, explorer):
    """Answers cost a request each, so they wait until the card is served."""
    created = card_builder.ensure_bootstrapped(conn, explorer)
    assert all(c.answer_uci is None for c in created)
    assert all(cards_repo.needs_answer(c) for c in created)


# -- preparation ---------------------------------------------------------
def test_preparing_resolves_the_answer(conn, explorer, fake_engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    prepared = card_builder.prepare_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert prepared.resolved_now
    assert prepared.card.answer_uci == "c7c5"
    assert prepared.card.answer_san == "c5"
    assert prepared.card.mode == CardMode.FREQUENCY.value


def test_preparing_costs_one_request(conn, explorer, fake_engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    before = explorer.call_count
    card_builder.prepare_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert explorer.call_count - before == 1


def test_preparing_twice_resolves_once(conn, explorer, fake_engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    first = card_builder.prepare_card(conn, explorer, fake_engine, card, engine_depth=10)
    second = card_builder.prepare_card(
        conn, explorer, fake_engine, first.card, engine_depth=10
    )
    assert not second.resolved_now
    assert second.card.answer_uci == first.card.answer_uci


def test_a_frequency_answer_is_decided_without_the_engine(conn, explorer, fake_engine):
    """The engine does not choose the answer -- frequency does.

    It is still consulted once, to find its own top move for the card's
    "is the most played move also the engine's?" line, and the answer is the
    most played move whatever it says.
    """
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    position = line_module.position_of(["e2e4"])
    engine = FakeEngine(best_moves={position.fen: "e7e5"})
    prepared = card_builder.prepare_card(
        conn, explorer, engine, card, engine_depth=10
    )
    assert prepared.card.answer_uci == "c7c5"  # the most played, not the engine's
    assert engine.call_count == 1


def test_preparing_resolves_the_engines_own_move(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    position = line_module.position_of(["e2e4"])
    engine = FakeEngine(best_moves={position.fen: "e7e5"})
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    assert prepared.engine_best_uci == "e7e5"


def test_re_serving_a_card_reads_the_engine_from_the_cache(conn, explorer):
    """A card seen before still reports the engine's move, without searching."""
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    position = line_module.position_of(["e2e4"])
    engine = FakeEngine(best_moves={position.fen: "e7e5"})
    first = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    calls = engine.call_count

    again = card_builder.prepare_card(
        conn, explorer, engine, first.card, engine_depth=10
    )
    assert again.engine_best_uci == "e7e5"
    assert engine.call_count == calls


def test_a_dead_end_is_never_searched(conn, explorer, fake_engine):
    thin_line = [*DEEP, "h2h3"]
    position = line_module.position_of(thin_line)
    card = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd, fen=position.fen, line_uci=position.line_uci,
            depth=position.depth, side_to_move=position.side_to_move,
            given_move_uci="h2h3", given_move_san="h3",
            status=cards_repo.STATUS_DEAD_END, position_games=11, queue_seq=1,
        ),
    )
    prepared = card_builder.prepare_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert prepared.engine_best_uci is None
    assert fake_engine.call_count == 0


# -- does the engine agree with the masters? -----------------------------
def test_engine_agrees_when_the_most_played_move_is_its_own(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    position = line_module.position_of(["e2e4"])
    engine = FakeEngine(best_moves={position.fen: "c7c5"})
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    assert card_builder.engine_agrees(prepared.card, prepared.engine_best_uci) is True


def test_engine_disagrees_when_it_prefers_another_move(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    position = line_module.position_of(["e2e4"])
    engine = FakeEngine(best_moves={position.fen: "e7e5"})
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    assert card_builder.engine_agrees(prepared.card, prepared.engine_best_uci) is False


def test_an_engine_mode_card_has_no_agreement_to_report(conn, explorer):
    """Its answer *is* the engine's move, so there is nothing to compare."""
    thin_line = [*DEEP, "h2h3"]
    position = line_module.position_of(thin_line)
    engine = FakeEngine(best_moves={position.fen: "d8d1"})
    card = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd, fen=position.fen, line_uci=position.line_uci,
            depth=position.depth, side_to_move=position.side_to_move,
            given_move_uci="h2h3", given_move_san="h3", status="active",
            position_games=11, queue_seq=1,
        ),
    )
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    assert prepared.card.mode == CardMode.ENGINE.value
    assert card_builder.engine_agrees(prepared.card, prepared.engine_best_uci) is None


def test_no_agreement_without_an_engine_result(conn, explorer, fake_engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    prepared = card_builder.prepare_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert card_builder.engine_agrees(prepared.card, None) is None


def test_preparing_records_the_opening_of_the_position(conn, explorer, fake_engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    prepared = card_builder.prepare_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert prepared.card.opening_label == "B00 King's Pawn Game"


# -- expansion -----------------------------------------------------------
def prepared_e4(conn, explorer, engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    return card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10).card


def test_expanding_creates_the_five_percent_branches(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    result = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert [c.given_move_san for c in result.new_cards] == ["c5", "e5", "e6", "c6"]


def test_expanding_costs_no_extra_requests(conn, explorer, fake_engine):
    """A parent's move counts are the children's totals, so nothing is fetched."""
    card = prepared_e4(conn, explorer, fake_engine)
    before = explorer.call_count
    card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert explorer.call_count == before


def test_children_inherit_their_game_counts_from_the_parent(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    result = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    by_move = {c.given_move_san: c for c in result.new_cards}
    assert by_move["c5"].position_games == 601092


def test_children_get_their_opening_names(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    result = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    by_move = {c.given_move_san: c for c in result.new_cards}
    assert by_move["c5"].opening_label == "B20 Sicilian Defense"
    assert by_move["c6"].opening_label == "B10 Caro-Kann Defense"


def test_children_are_one_deeper_and_sequenced_in_order(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    result = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert all(c.depth == 2 for c in result.new_cards)
    seqs = [c.queue_seq for c in result.new_cards]
    assert seqs == sorted(seqs)
    assert min(seqs) > 20  # after every depth-1 card


def test_children_point_at_their_parent(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    result = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert all(c.parent_card_id == card.id for c in result.new_cards)


def test_expanding_marks_the_card_expanded(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert cards_repo.get(conn, card.id).is_expanded


def test_expanding_twice_is_a_no_op(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    again = card_builder.expand_card(
        conn, explorer, fake_engine, cards_repo.get(conn, card.id), engine_depth=10
    )
    assert again.already_expanded
    assert again.created == 0


def test_breadth_first_order_is_preserved(conn, explorer, fake_engine):
    """After expanding 1.e4, the next new card is still a depth-1 card."""
    card = prepared_e4(conn, explorer, fake_engine)
    from chess_trainer.db import schedule_repo
    from datetime import date

    schedule_repo.upsert(
        conn,
        schedule_repo.ScheduleRow(
            card_id=card.id, n=1, ef=2.5, interval_days=1, due_on=date(2099, 1, 1)
        ),
    )
    card_builder.expand_card(conn, explorer, fake_engine, card, engine_depth=10)
    assert cards_repo.next_new_card(conn).depth == 1


# -- dead ends -----------------------------------------------------------
DEEP = [
    "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6",
    "e1g1", "f6e4", "d2d4", "e4d6", "b5c6", "d7c6",
    "d4e5", "d6f5",
]


def deep_card(conn, explorer, engine):
    position = line_module.position_of(DEEP)
    card = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd,
            fen=position.fen,
            line_uci=position.line_uci,
            depth=position.depth,
            side_to_move=position.side_to_move,
            given_move_uci=DEEP[-1],
            given_move_san="Nf5",
            status="active",
            position_games=8879,
            queue_seq=1,
        ),
    )
    return card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10).card


def test_a_deep_position_branches_only_above_five_percent(conn, explorer, fake_engine):
    card = deep_card(conn, explorer, fake_engine)
    result = card_builder.expand_card(
        conn, explorer, fake_engine, card, engine_depth=10
    )
    assert [c.given_move_san for c in result.new_cards] == ["Qxd8+"]
    assert result.dead_ends == []  # the thin moves are below 5%, so never branches


def test_a_thin_branch_becomes_a_dead_end(conn, explorer, fake_engine, explorer_deep):
    """Force an under-5-game move to be a branch and confirm it dead-ends."""
    from chess_trainer.explorer.explorer_types import PositionStats
    from chess_trainer.openings import tree_rules

    card = deep_card(conn, explorer, fake_engine)
    stats = PositionStats.of(explorer_deep)
    thin = next(m for m in stats.moves if m.games < tree_rules.MIN_GAMES)
    branches = tree_rules.engine_branch(thin.uci, stats)
    created = card_builder._create_children(
        conn,
        parent=card,
        parent_position=line_module.position_of(DEEP),
        plan=tree_rules.plan_position(stats),
        stats=stats,
        branches=branches,
    )
    assert len(created) == 1
    assert created[0].is_dead_end
    assert created[0].position_games == thin.games
    assert cards_repo.dead_end_children(conn, card.id) == created


def test_dead_ends_are_never_served_as_new_cards(conn, explorer, fake_engine, explorer_deep):
    from chess_trainer.explorer.explorer_types import PositionStats
    from chess_trainer.openings import tree_rules

    card = deep_card(conn, explorer, fake_engine)
    stats = PositionStats.of(explorer_deep)
    thin = next(m for m in stats.moves if m.games < tree_rules.MIN_GAMES)
    card_builder._create_children(
        conn,
        parent=card,
        parent_position=line_module.position_of(DEEP),
        plan=tree_rules.plan_position(stats),
        stats=stats,
        branches=tree_rules.engine_branch(thin.uci, stats),
    )
    for _ in range(5):
        nxt = cards_repo.next_new_card(conn)
        if nxt is None:
            break
        assert not nxt.is_dead_end


# -- engine mode ---------------------------------------------------------
def test_an_engine_mode_card_is_answered_by_the_engine(conn, explorer):
    thin_line = [*DEEP, "h2h3"]
    position = line_module.position_of(thin_line)
    engine = FakeEngine(best_moves={position.fen: "d8d1"})
    card = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd,
            fen=position.fen,
            line_uci=position.line_uci,
            depth=position.depth,
            side_to_move=position.side_to_move,
            given_move_uci="h2h3",
            given_move_san="h3",
            status="active",
            position_games=11,
            queue_seq=1,
        ),
    )
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    assert prepared.card.mode == CardMode.ENGINE.value
    assert prepared.card.answer_uci == "d8d1"
    # The answer and the engine's own move are the same search, cached.
    assert engine.call_count == 1


def test_an_engine_mode_card_has_exactly_one_branch(conn, explorer):
    thin_line = [*DEEP, "h2h3"]
    position = line_module.position_of(thin_line)
    engine = FakeEngine(best_moves={position.fen: "d8d1"})
    card = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd, fen=position.fen, line_uci=position.line_uci,
            depth=position.depth, side_to_move=position.side_to_move,
            given_move_uci="h2h3", given_move_san="h3", status="active",
            position_games=11, queue_seq=1,
        ),
    )
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    result = card_builder.expand_card(
        conn, explorer, engine, prepared.card, engine_depth=10
    )
    assert result.created == 1
    assert (result.new_cards + result.dead_ends)[0].given_move_uci == "d8d1"


# -- ties ----------------------------------------------------------------
def test_a_tie_is_broken_by_the_engine_and_recorded(conn):
    """Two moves played equally often: Stockfish chooses and the tie is noted."""
    position = line_module.position_of(["e2e4"])
    payload = {
        "white": 100,
        "draws": 0,
        "black": 0,
        "opening": {"eco": "B00", "name": "King's Pawn Game"},
        "moves": [
            {"uci": "c7c5", "san": "c5", "white": 50, "draws": 0, "black": 0},
            {"uci": "e7e5", "san": "e5", "white": 50, "draws": 0, "black": 0},
        ],
    }
    explorer = FakeExplorer({position.epd: payload})
    engine = FakeEngine(best_moves={position.fen: "e7e5"})
    card = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=position.epd, fen=position.fen, line_uci=position.line_uci,
            depth=1, side_to_move="black", given_move_uci="e2e4",
            given_move_san="e4", status="active", position_games=100, queue_seq=1,
        ),
    )
    prepared = card_builder.prepare_card(conn, explorer, engine, card, engine_depth=10)
    assert prepared.card.answer_uci == "e7e5"
    assert set(prepared.card.tied_ucis) == {"c7c5", "e7e5"}
    # One search among the tied moves, one for the engine's own top move.
    assert engine.call_count == 2


# -- transpositions ------------------------------------------------------
def test_a_transposition_does_not_become_a_second_card(conn):
    """One position, one card -- even reached by two move orders."""
    first = line_module.position_of(["g1f3", "d7d5", "d2d4"])
    second = line_module.position_of(["d2d4", "d7d5", "g1f3"])
    assert first.epd == second.epd

    row = cards_repo.CardRow(
        epd=first.epd, fen=first.fen, line_uci=first.line_uci, depth=3,
        side_to_move="black", given_move_uci="d2d4", given_move_san="d4",
        status="active", position_games=1000, queue_seq=1,
    )
    created = cards_repo.insert(conn, row)
    duplicate = cards_repo.insert(
        conn,
        cards_repo.CardRow(
            epd=second.epd, fen=second.fen, line_uci=second.line_uci, depth=3,
            side_to_move="black", given_move_uci="g1f3", given_move_san="Nf3",
            status="active", position_games=1000, queue_seq=2,
        ),
    )
    assert duplicate.id == created.id
    assert cards_repo.count(conn) == 1


# -- caching -------------------------------------------------------------
def test_responses_are_cached_in_the_database(conn, explorer, fake_engine):
    card_builder.ensure_bootstrapped(conn, explorer)
    assert explorer_repo.count(conn) == 1
    assert explorer_repo.get(conn, epd_of([])) is not None


def test_cached_stats_need_no_source(conn, explorer, fake_engine):
    card = prepared_e4(conn, explorer, fake_engine)
    assert card_builder.cached_stats_for_card(conn, card) is not None


def test_cached_stats_of_an_unknown_position_is_none(conn, explorer):
    card_builder.ensure_bootstrapped(conn, explorer)
    card = cards_repo.next_new_card(conn)
    assert card_builder.cached_stats_for_card(conn, card) is None
