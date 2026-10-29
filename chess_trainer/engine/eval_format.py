"""Human-readable evaluation strings for the eval bar.

Always rendered from **White's** perspective, as the spec requires:
``+0.45``, ``−1.20``, ``M3`` (White mates in 3), ``−M3`` (Black mates in 3).

The minus sign is U+2212 MINUS SIGN rather than a hyphen, which lines up with
the plus sign in a proportional font.
"""

from __future__ import annotations

from chess_trainer.engine.eval_types import Eval

MINUS = "−"
PLUS = "+"

#: Fraction of the bar filled, clamped so the bar never fully empties.
BAR_MIN = 0.02
BAR_MAX = 0.98


def format_eval(evaluation: Eval) -> str:
    """Format an evaluation for display, from White's perspective."""
    if evaluation.mate is not None:
        moves = abs(evaluation.mate)
        sign = "" if evaluation.mate > 0 else MINUS
        return f"{sign}M{moves}"

    assert evaluation.cp is not None
    pawns = evaluation.cp / 100
    if evaluation.cp == 0:
        return "0.00"
    sign = PLUS if evaluation.cp > 0 else MINUS
    return f"{sign}{abs(pawns):.2f}"


def bar_fraction(evaluation: Eval) -> float:
    """How much of the eval bar White fills, in ``0..1``.

    Uses the win-percentage curve so the bar moves the way Lichess's does.
    Imported lazily to keep this module's import graph trivial.
    """
    from chess_trainer.engine.winpct import win_percent

    pct = win_percent(evaluation, white_to_move=True) / 100
    return max(BAR_MIN, min(BAR_MAX, pct))
