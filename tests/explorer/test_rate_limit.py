"""Throttling and back-off, with an injected clock: no real waiting."""

from __future__ import annotations

import threading

import pytest

from chess_trainer.explorer.rate_limit import (
    MIN_INTERVAL_SECONDS,
    RATE_LIMIT_BACKOFF_SECONDS,
    Throttle,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def throttle(clock: FakeClock, interval: float = 1.0) -> Throttle:
    return Throttle(min_interval=interval, sleep=clock.sleep, monotonic=clock.monotonic)


def test_the_first_call_does_not_wait():
    clock = FakeClock()
    assert throttle(clock).wait() == 0.0
    assert clock.slept == []


def test_an_immediate_second_call_waits_the_interval():
    clock = FakeClock()
    t = throttle(clock, interval=1.0)
    t.wait()
    assert t.wait() == pytest.approx(1.0)
    assert clock.slept == [1.0]


def test_a_late_second_call_does_not_wait():
    clock = FakeClock()
    t = throttle(clock, interval=1.0)
    t.wait()
    clock.now += 5.0
    assert t.wait() == 0.0
    assert clock.slept == []


def test_successive_calls_are_spaced_out():
    clock = FakeClock()
    t = throttle(clock, interval=0.5)
    for _ in range(4):
        t.wait()
    assert clock.slept == [0.5, 0.5, 0.5]


def test_a_partial_wait_only_covers_the_remainder():
    clock = FakeClock()
    t = throttle(clock, interval=1.0)
    t.wait()
    clock.now += 0.4
    assert t.wait() == pytest.approx(0.6)


def test_penalise_pushes_the_next_call_out():
    clock = FakeClock()
    t = throttle(clock, interval=1.0)
    t.wait()
    t.penalise(60.0)
    assert t.wait() == pytest.approx(60.0)


def test_the_spec_backoff_is_sixty_seconds():
    assert RATE_LIMIT_BACKOFF_SECONDS == 60.0


def test_the_default_interval_is_gentle():
    assert 0 < MIN_INTERVAL_SECONDS <= 2.0


def test_the_throttle_is_thread_safe():
    """Card expansion can run in a worker thread while a request is served."""
    t = Throttle(min_interval=0.001)
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        try:
            for _ in range(20):
                t.wait()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
