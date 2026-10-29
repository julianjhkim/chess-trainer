"""Session state: which steps are selected, which are done, where we are.

A small mutable state machine, kept free of I/O so it can be driven directly in
tests. The API layer owns one instance per server process (the app is
single-user and localhost-only) and persists only the streak side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chess_trainer.session.steps import (
    DEFAULT_ENABLED,
    ORDER,
    Step,
    StepInfo,
    first_enabled,
    next_after,
    sort_steps,
)


@dataclass(slots=True)
class SessionFlow:
    """Tracks progress through one session."""

    enabled: set[Step] = field(default_factory=lambda: set(DEFAULT_ENABLED))
    completed: set[Step] = field(default_factory=set)
    current: Step | None = None
    started: bool = False

    # -- lifecycle -------------------------------------------------------
    def start(self, enabled: set[Step] | frozenset[Step] | None = None) -> Step | None:
        """Begin a session with the given steps selected (default: all four)."""
        if enabled is not None:
            self.enabled = set(enabled)
        self.completed = set()
        self.started = True
        self.current = first_enabled(self.enabled)
        return self.current

    def reset(self) -> None:
        self.enabled = set(DEFAULT_ENABLED)
        self.completed = set()
        self.current = None
        self.started = False

    # -- navigation ------------------------------------------------------
    def jump_to(self, step: Step) -> Step:
        """Move to any step, forwards or backwards.

        Clicking a step that was left unchecked on the start screen selects it,
        rather than refusing: the step bar is an escape hatch, so it should
        always do what it looks like it does.
        """
        self.enabled.add(step)
        self.started = True
        self.current = step
        return step

    def complete_current(self) -> Step | None:
        """Mark the current step done and advance to the next enabled one."""
        if self.current is None:
            return None
        return self.complete(self.current)

    def complete(self, step: Step) -> Step | None:
        """Mark ``step`` done; if it was current, advance. Returns the new current."""
        self.completed.add(step)
        if self.current is step:
            self.current = next_after(step, self.enabled)
        return self.current

    def uncomplete(self, step: Step) -> None:
        """Forget that a step was completed (used when re-running it)."""
        self.completed.discard(step)

    @property
    def is_finished(self) -> bool:
        """True once every enabled step has been completed."""
        return self.started and self.enabled.issubset(self.completed)

    @property
    def remaining(self) -> list[Step]:
        return [s for s in sort_steps(self.enabled) if s not in self.completed]

    # -- presentation ----------------------------------------------------
    def step_bar(self) -> list[StepInfo]:
        """All four steps, for rendering the step bar."""
        return [
            StepInfo(
                step=step,
                position=step.position,
                title=step.title,
                enabled=step in self.enabled,
                completed=step in self.completed,
                current=step is self.current,
            )
            for step in ORDER
        ]
