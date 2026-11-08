"""The background scan: progress, outcome, cancelling."""

from __future__ import annotations

import threading

from chess_trainer.api.scan_job import ScanJob
from chess_trainer.inaccuracies.scan import ScanCancelled


def test_a_job_reports_its_result():
    job = ScanJob(lambda job: 42).start()
    job.cancel()  # joins
    assert (job.status, job.result) == ("done", 42)


def test_a_failure_is_reported_not_raised():
    def boom(job):
        raise RuntimeError("engine fell over")

    job = ScanJob(boom).start()
    job.cancel()
    assert (job.status, job.error) == ("failed", "engine fell over")


def test_cancelling_stops_the_work_and_waits_for_it():
    started = threading.Event()

    def work(job):
        started.set()
        while not job.cancelled:
            pass
        raise ScanCancelled

    job = ScanJob(work).start()
    started.wait(1)
    job.cancel()
    assert job.status == "cancelled"
    assert not job._thread.is_alive()
