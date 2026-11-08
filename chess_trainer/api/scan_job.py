"""A game scan running in the background, with progress for the page to poll.

One scan at a time. The work itself is handed in as a function, so this only
does the threading: progress, the outcome, cancelling. ``AppState.shutdown``
cancels and joins it before closing the engine and the database -- a thread
left running past the connection crashes the process.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"


class ScanJob:
    def __init__(self, work: Callable[["ScanJob"], Any]) -> None:
        self.status = RUNNING
        self.done = 0
        self.total = 0
        self.result: Any = None
        self.error: str | None = None
        #: Set once the outcome has been reported (step and streak counted).
        self.reported = False
        self._cancel = threading.Event()
        self._work = work
        self._thread = threading.Thread(target=self._run, name="puzzle-scan", daemon=True)

    def start(self) -> "ScanJob":
        self._thread.start()
        return self

    def progress(self, done: int, total: int) -> None:
        self.done, self.total = done, total

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def running(self) -> bool:
        return self.status == RUNNING

    def cancel(self, *, wait: bool = True) -> None:
        self._cancel.set()
        if wait and self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        from chess_trainer.inaccuracies.scan import ScanCancelled

        try:
            self.result = self._work(self)
            self.status = DONE
        except ScanCancelled:
            self.status = CANCELLED
        except Exception as exc:  # reported to the page, not raised
            self.error = str(exc) or exc.__class__.__name__
            self.status = FAILED
