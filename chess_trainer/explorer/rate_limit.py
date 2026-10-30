"""Throttling for the explorer, and the 429 back-off the spec asks for.

Both the clock and the sleep are injectable, so the waiting behaviour is tested
without actually waiting.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

#: Minimum gap between explorer requests. The masters database barely changes
#: and almost everything is served from the local cache, so being gentle here
#: costs nothing.
MIN_INTERVAL_SECONDS = 0.6

#: What the spec requires after an HTTP 429.
RATE_LIMIT_BACKOFF_SECONDS = 60.0


@dataclass
class Throttle:
    """Keeps successive calls at least ``min_interval`` apart.

    Thread-safe: card expansion can run in a worker thread while a request is
    being served.
    """

    min_interval: float = MIN_INTERVAL_SECONDS
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _last_call: float | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def wait(self) -> float:
        """Block until the next call is allowed. Returns how long it waited."""
        with self._lock:
            now = self.monotonic()
            if self._last_call is None:
                self._last_call = now
                return 0.0
            earliest = self._last_call + self.min_interval
            delay = earliest - now
            if delay > 0:
                self.sleep(delay)
                self._last_call = earliest
                return delay
            self._last_call = now
            return 0.0

    def penalise(self, seconds: float = RATE_LIMIT_BACKOFF_SECONDS) -> None:
        """Push the next allowed call out by ``seconds`` (used after a 429)."""
        with self._lock:
            self._last_call = self.monotonic() + seconds - self.min_interval
