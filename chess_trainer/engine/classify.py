"""Turn a win-percentage drop into a move classification.

Thresholds follow Lichess: a drop of 10 points is an inaccuracy, 20 a mistake,
30 a blunder.
"""

from __future__ import annotations

from enum import Enum

INACCURACY_THRESHOLD = 10.0
MISTAKE_THRESHOLD = 20.0
BLUNDER_THRESHOLD = 30.0


class Classification(Enum):
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"

    @property
    def is_inaccuracy_or_worse(self) -> bool:
        return self is not Classification.GOOD

    @property
    def label(self) -> str:
        return self.value.capitalize()


def classify(win_percent_drop: float) -> Classification:
    """Classify a move by how much win percentage it conceded."""
    if win_percent_drop >= BLUNDER_THRESHOLD:
        return Classification.BLUNDER
    if win_percent_drop >= MISTAKE_THRESHOLD:
        return Classification.MISTAKE
    if win_percent_drop >= INACCURACY_THRESHOLD:
        return Classification.INACCURACY
    return Classification.GOOD
