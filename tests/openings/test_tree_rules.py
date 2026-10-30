"""The card rules: the games table, the root exception, and branch selection."""

from __future__ import annotations

from chess_trainer.explorer.explorer_types import PositionStats
from chess_trainer.openings import tree_rules
from chess_trainer.openings.card_types import CardMode, CardStatus


def stats(total: int, moves: list[tuple[str, int]]) -> PositionStats:
    """A position with ``total`` games and the given (uci, games) moves."""
    return PositionStats.of(
        {
            "white": total,
            "draws": 0,
            "black": 0,
            "moves": [
                {"uci": uci, "san": uci, "white": games, "draws": 0, "black": 0}
                for uci, games in moves
            ],
        }
    )


# -- thresholds ----------------------------------------------------------
def test_the_spec_thresholds():
    assert tree_rules.FREQUENCY_THRESHOLD == 20
    assert tree_rules.MIN_GAMES == 5
    assert tree_rules.BRANCH_SHARE_PERCENT == 5.0


def test_under_five_games_is_not_a_card():
    plan = tree_rules.plan_position(stats(4, [("e2e4", 4)]))
    assert plan.status is CardStatus.DEAD_END
    assert not plan.is_card
    assert plan.branches == ()


def test_zero_games_is_not_a_card():
    assert tree_rules.plan_position(stats(0, [])).status is CardStatus.DEAD_END


def test_exactly_five_games_is_a_card():
    plan = tree_rules.plan_position(stats(5, [("e2e4", 5)]))
    assert plan.is_card
    assert plan.mode is CardMode.ENGINE


def test_five_to_nineteen_games_uses_the_engine():
    for total in (5, 10, 19):
        plan = tree_rules.plan_position(stats(total, [("e2e4", total)]))
        assert plan.mode is CardMode.ENGINE, total
        assert plan.needs_engine
        assert plan.answer_candidates == ()
        assert plan.branches == ()


def test_twenty_games_uses_frequency():
    plan = tree_rules.plan_position(stats(20, [("e2e4", 20)]))
    assert plan.mode is CardMode.FREQUENCY
    assert plan.answer_candidates == ("e2e4",)
    assert not plan.needs_engine


def test_a_busy_position_uses_frequency():
    plan = tree_rules.plan_position(stats(1000, [("e2e4", 600), ("d2d4", 400)]))
    assert plan.mode is CardMode.FREQUENCY
    assert plan.answer_candidates == ("e2e4",)


def test_enough_games_but_no_recorded_continuation_stops():
    """Games reached here but the database records no move onwards."""
    assert tree_rules.plan_position(stats(500, [])).status is CardStatus.DEAD_END


# -- branches ------------------------------------------------------------
def test_branches_need_five_percent():
    position = stats(1000, [("a", 600), ("b", 300), ("c", 60), ("d", 40)])
    plan = tree_rules.plan_position(position)
    assert [b.uci for b in plan.branches] == ["a", "b", "c"]  # d is 4%


def test_a_branch_at_exactly_five_percent_is_included():
    plan = tree_rules.plan_position(stats(1000, [("a", 950), ("b", 50)]))
    assert [b.uci for b in plan.branches] == ["a", "b"]


def test_branches_are_most_played_first():
    plan = tree_rules.plan_position(stats(1000, [("a", 100), ("b", 600), ("c", 300)]))
    assert [b.uci for b in plan.branches] == ["b", "c", "a"]


def test_branch_shares_are_reported():
    plan = tree_rules.plan_position(stats(1000, [("a", 600), ("b", 400)]))
    assert plan.branches[0].share == 60.0
    assert plan.branches[0].games == 600


def test_a_position_where_nothing_reaches_five_percent_has_no_branches():
    moves = [(chr(ord("a") + i), 1) for i in range(25)]
    plan = tree_rules.plan_position(stats(25, moves))
    assert plan.branches == ()


# -- ties ----------------------------------------------------------------
def test_a_single_most_played_move_needs_no_engine():
    plan = tree_rules.plan_position(stats(1000, [("a", 600), ("b", 400)]))
    assert plan.answer_candidates == ("a",)
    assert not plan.needs_engine


def test_a_tie_is_handed_to_the_engine():
    plan = tree_rules.plan_position(stats(1000, [("a", 500), ("b", 500)]))
    assert set(plan.answer_candidates) == {"a", "b"}
    assert plan.needs_engine


def test_a_three_way_tie():
    plan = tree_rules.plan_position(stats(900, [("a", 300), ("b", 300), ("c", 300)]))
    assert len(plan.answer_candidates) == 3


def test_only_the_tied_top_moves_are_candidates():
    plan = tree_rules.plan_position(stats(1000, [("a", 400), ("b", 400), ("c", 200)]))
    assert set(plan.answer_candidates) == {"a", "b"}


def test_most_frequent_candidates_of_nothing_is_empty():
    assert tree_rules.most_frequent_candidates(stats(0, [])) == ()


# -- the root exception --------------------------------------------------
def test_the_root_is_not_a_card():
    plan = tree_rules.plan_root(stats(1000, [("e2e4", 500)]))
    assert plan.is_root
    assert not plan.is_card
    assert plan.answer_candidates == ()


def test_the_root_branches_on_every_move_with_no_share_filter():
    position = stats(1000, [("a", 500), ("b", 490), ("c", 9), ("d", 1)])
    plan = tree_rules.plan_root(position)
    assert [b.uci for b in plan.branches] == ["a", "b", "c", "d"]


def test_the_root_branches_are_ordered_by_game_count():
    plan = tree_rules.plan_root(stats(100, [("a", 10), ("b", 60), ("c", 30)]))
    assert [b.uci for b in plan.branches] == ["b", "c", "a"]


def test_plan_position_with_is_root_delegates_to_plan_root():
    position = stats(1000, [("a", 999), ("b", 1)])
    assert tree_rules.plan_position(position, is_root=True) == tree_rules.plan_root(position)


# -- engine-mode branch --------------------------------------------------
def test_the_engine_branch_is_the_engine_move():
    position = stats(10, [("e2e4", 7), ("d2d4", 3)])
    branches = tree_rules.engine_branch("e2e4", position)
    assert [b.uci for b in branches] == ["e2e4"]
    assert branches[0].games == 7


def test_an_engine_move_absent_from_the_database_has_no_games():
    branches = tree_rules.engine_branch("h2h4", stats(10, [("e2e4", 10)]))
    assert branches[0].games == 0
    assert branches[0].share == 0.0


# -- descriptions --------------------------------------------------------
def test_threshold_descriptions():
    assert "only 1 master game" == tree_rules.describe_threshold(1)
    assert "only 4 master games" == tree_rules.describe_threshold(4)
    assert "too few to trust frequency" in tree_rules.describe_threshold(12)
    assert tree_rules.describe_threshold(500) == "500 master games"


# -- the real data -------------------------------------------------------
def test_the_real_root(explorer_root):
    position = PositionStats.of(explorer_root)
    plan = tree_rules.plan_root(position)
    assert plan.is_root
    assert len(plan.branches) == 20  # every first move, no filter
    assert plan.branches[0].uci == "e2e4"
    assert plan.branches[-1].games < 20  # rare first moves still branch


def test_the_real_e4_position(explorer_e4):
    plan = tree_rules.plan_position(PositionStats.of(explorer_e4))
    assert plan.mode is CardMode.FREQUENCY
    assert plan.answer_candidates == ("c7c5",)
    assert [b.uci for b in plan.branches] == ["c7c5", "e7e5", "e7e6", "c7c6"]


def test_a_real_deep_position_filters_hard(explorer_deep):
    """8879 games, but one move accounts for 98.6% so only it branches."""
    plan = tree_rules.plan_position(PositionStats.of(explorer_deep))
    assert plan.mode is CardMode.FREQUENCY
    assert [b.uci for b in plan.branches] == ["d1d8"]
    assert plan.answer_candidates == ("d1d8",)


def test_a_real_thin_position_is_engine_mode(explorer_thin):
    plan = tree_rules.plan_position(PositionStats.of(explorer_thin))
    assert plan.total_games == 11
    assert plan.mode is CardMode.ENGINE
    assert plan.needs_engine


def test_real_dead_end_detection_from_a_parents_counts(explorer_deep):
    position = PositionStats.of(explorer_deep)
    thin = [m for m in position.moves if m.games < tree_rules.MIN_GAMES]
    assert {m.san for m in thin} >= {"Nbd2", "Bg5"}
