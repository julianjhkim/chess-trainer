from __future__ import annotations

from chess_trainer.session.flow import SessionFlow
from chess_trainer.session.steps import ORDER, Step


def test_a_new_flow_has_not_started():
    flow = SessionFlow()
    assert not flow.started
    assert flow.current is None


def test_start_selects_the_first_step():
    flow = SessionFlow()
    assert flow.start() is Step.REVIEW_LAST_GAME
    assert flow.started


def test_start_with_a_subset_begins_at_the_earliest_selected():
    flow = SessionFlow()
    assert flow.start({Step.REVIEW_NEW_GAME, Step.CARDS}) is Step.REVIEW_NEW_GAME


def test_start_with_an_empty_selection_has_no_current_step():
    assert SessionFlow().start(set()) is None


def test_completing_advances_to_the_next_step():
    flow = SessionFlow()
    flow.start()
    assert flow.complete_current() is Step.PLAY


def test_finishing_the_play_step_moves_to_the_review_step():
    """The spec requires step 2 to hand straight over to step 3."""
    flow = SessionFlow()
    flow.start()
    flow.complete(Step.REVIEW_LAST_GAME)
    assert flow.complete(Step.PLAY) is Step.REVIEW_NEW_GAME


def test_completing_skips_unselected_steps():
    flow = SessionFlow()
    flow.start({Step.REVIEW_LAST_GAME, Step.CARDS})
    assert flow.complete_current() is Step.CARDS


def test_after_the_last_step_there_is_no_current():
    flow = SessionFlow()
    flow.start({Step.CARDS})
    assert flow.complete_current() is None
    assert flow.is_finished


def test_complete_current_without_a_current_step_is_safe():
    assert SessionFlow().complete_current() is None


def test_jump_moves_forward():
    flow = SessionFlow()
    flow.start()
    assert flow.jump_to(Step.CARDS) is Step.CARDS
    assert flow.current is Step.CARDS


def test_jump_moves_backward():
    flow = SessionFlow()
    flow.start()
    flow.complete_current()
    flow.jump_to(Step.REVIEW_LAST_GAME)
    assert flow.current is Step.REVIEW_LAST_GAME


def test_jumping_to_an_unselected_step_selects_it():
    flow = SessionFlow()
    flow.start({Step.CARDS})
    flow.jump_to(Step.PLAY)
    assert Step.PLAY in flow.enabled


def test_jumping_does_not_clear_completion():
    flow = SessionFlow()
    flow.start()
    flow.complete(Step.REVIEW_LAST_GAME)
    flow.jump_to(Step.REVIEW_LAST_GAME)
    assert Step.REVIEW_LAST_GAME in flow.completed


def test_uncomplete_allows_rerunning_a_step():
    flow = SessionFlow()
    flow.start()
    flow.complete(Step.REVIEW_LAST_GAME)
    flow.uncomplete(Step.REVIEW_LAST_GAME)
    assert Step.REVIEW_LAST_GAME not in flow.completed
    assert not flow.is_finished


def test_is_finished_requires_every_selected_step():
    flow = SessionFlow()
    flow.start({Step.PLAY, Step.CARDS})
    flow.complete(Step.PLAY)
    assert not flow.is_finished
    flow.complete(Step.CARDS)
    assert flow.is_finished


def test_a_flow_that_never_started_is_not_finished():
    assert not SessionFlow().is_finished


def test_remaining_lists_outstanding_steps_in_order():
    flow = SessionFlow()
    flow.start()
    flow.complete(Step.PLAY)
    assert flow.remaining == [Step.REVIEW_LAST_GAME, Step.REVIEW_NEW_GAME, Step.CARDS]


def test_reset_clears_everything():
    flow = SessionFlow()
    flow.start({Step.CARDS})
    flow.complete_current()
    flow.reset()
    assert not flow.started
    assert flow.completed == set()
    assert flow.enabled == set(ORDER)


def test_step_bar_always_shows_all_four_steps():
    flow = SessionFlow()
    flow.start({Step.CARDS})
    bar = flow.step_bar()
    assert len(bar) == 4
    assert [i.position for i in bar] == [1, 2, 3, 4]


def test_step_bar_flags_state_correctly():
    flow = SessionFlow()
    flow.start({Step.REVIEW_LAST_GAME, Step.PLAY})
    flow.complete(Step.REVIEW_LAST_GAME)
    bar = {info.step: info for info in flow.step_bar()}
    assert bar[Step.REVIEW_LAST_GAME].completed
    assert bar[Step.PLAY].current
    assert not bar[Step.CARDS].enabled
