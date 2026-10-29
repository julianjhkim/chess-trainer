"""Lichess's win-percentage model.

    Win% = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)

``cp`` is centipawns **from the mover's perspective**. Lichess caps the
centipawn value before applying the curve, so that two overwhelmingly winning
positions do not register a swing between them; we keep that behaviour.
"""

from __future__ import annotations

import math

from chess_trainer.engine.eval_types import Eval

#: The constant from Lichess's formula.
MULTIPLIER = -0.00368208

#: Centipawn values beyond this are treated as equivalent (Lichess's ceiling).
CP_CEILING = 1000


def win_percent_from_cp(cp: float) -> float:
    """Win percentage (0..100) for a centipawn score from the mover's view."""
    capped = max(-CP_CEILING, min(CP_CEILING, cp))
    return 50 + 50 * (2 / (1 + math.exp(MULTIPLIER * capped)) - 1)


def win_percent(evaluation: Eval, *, white_to_move: bool) -> float:
    """Win percentage for the side to move.

    A mate for the mover is 100, a mate against the mover is 0.
    """
    pov = evaluation.pov(white_to_move)
    if pov.mate is not None:
        return 100.0 if pov.mate > 0 else 0.0
    assert pov.cp is not None
    return win_percent_from_cp(pov.cp)


def win_percent_drop(
    before: Eval, after: Eval, *, mover_is_white: bool
) -> float:
    """How much win percentage the mover gave up by playing their move.

    ``before`` is the position with the mover to move; ``after`` is the position
    once they have moved (so the *opponent* is to move). Both are White's-view
    evaluations. The result is clamped at 0: a move that improves the engine's
    assessment is not a mistake.
    """
    pct_before = win_percent(before, white_to_move=mover_is_white)
    # After the move it is the opponent's turn, but we still want the mover's view.
    pct_after = win_percent(after, white_to_move=mover_is_white)
    return max(0.0, pct_before - pct_after)
