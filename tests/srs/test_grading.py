from __future__ import annotations

from chess_trainer.srs import grading


def test_right_first_time_is_four():
    assert grading.quality_for(attempts=1, used_show_answer=False) == 4


def test_right_on_the_second_try_is_three():
    assert grading.quality_for(attempts=2, used_show_answer=False) == 3


def test_right_on_the_third_try_or_later_is_two():
    assert grading.quality_for(attempts=3, used_show_answer=False) == 2
    assert grading.quality_for(attempts=9, used_show_answer=False) == 2


def test_a_revealed_answer_is_one():
    assert grading.quality_for(attempts=1, used_show_answer=True) == 1


def test_revealing_wins_over_the_attempt_count():
    assert grading.quality_for(attempts=1, used_show_answer=True) == 1
    assert grading.quality_for(attempts=5, used_show_answer=True) == 1


def test_zero_attempts_counts_as_a_first_try():
    assert grading.quality_for(attempts=0, used_show_answer=False) == 4


def test_passing_grades():
    assert grading.is_pass(4)
    assert grading.is_pass(3)


def test_failing_grades():
    assert not grading.is_pass(2)
    assert not grading.is_pass(1)
    assert not grading.is_pass(0)


def test_one_wrong_try_is_still_a_pass():
    assert grading.is_pass(grading.quality_for(attempts=2, used_show_answer=False))


def test_two_or_more_wrong_tries_fail_the_card():
    assert not grading.is_pass(grading.quality_for(attempts=3, used_show_answer=False))
    assert not grading.is_pass(grading.quality_for(attempts=4, used_show_answer=False))


def test_revealing_fails_the_card():
    assert not grading.is_pass(
        grading.quality_for(attempts=1, used_show_answer=True)
    )


def test_descriptions_are_readable():
    assert grading.describe(4) == "right first time"
    assert grading.describe(3) == "right on the 2nd try"
    assert grading.describe(1) == "answer revealed"
    assert "2" in grading.describe(2)


def test_a_fail_after_retries_counts_the_wrong_tries():
    assert grading.describe(2, attempts=4) == "right after 3 wrong tries"
    assert grading.describe(2, attempts=3) == "right after 2 wrong tries"


def test_a_hint_caps_a_first_try_at_three():
    assert grading.quality_for(attempts=1, used_show_answer=False, used_hint=True) == 3
    assert grading.describe(3, 1, used_hint=True) == "right with a hint"


def test_a_hint_does_not_rescue_a_third_try():
    assert grading.quality_for(attempts=3, used_show_answer=False, used_hint=True) == 2
