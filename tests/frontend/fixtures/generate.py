"""Generate the canned board-rules fixture the stub server serves.

The click-mapping test (``tests/frontend/click_map.mjs``) runs the real
frontend in a real browser against a stub API, so it needs the same legal
destinations and move results the Python backend would return — without a
server, an engine or a database. This writes them once, from the authoritative
rules module, for the handful of positions that test visits.

    python3 tests/frontend/fixtures/generate.py
"""

from __future__ import annotations

import json
from pathlib import Path

from chess_trainer import rules

#: Lines the test plays through. Every position along them gets a state, and
#: every move along them a move result.
LINES = [
    ["e2e4", "e7e5"],
]

OUT = Path(__file__).with_name("board.json")


def state_of(fen: str) -> dict:
    state = rules.position_state(fen)
    return {
        "fen": state.fen,
        "turn": state.turn,
        "dests": state.dests,
        "in_check": state.in_check,
        "game_over": state.game_over,
        "outcome": state.outcome,
    }


def main() -> None:
    states: dict[str, dict] = {}
    moves: dict[str, dict] = {}

    for line in LINES:
        fen = rules.START_FEN
        states[fen] = state_of(fen)
        for uci in line:
            result = rules.apply_move(fen, uci)
            moves[f"{fen}|{uci}"] = {
                "fen": result.fen_after,
                "uci": result.uci,
                "san": result.san,
                "promotion": result.promotion,
                "is_capture": result.is_capture,
                "game_over": result.game_over,
                "outcome": result.outcome,
                "state_fen": result.fen_after,
            }
            fen = result.fen_after
            states[fen] = state_of(fen)

    OUT.write_text(
        json.dumps({"states": states, "moves": moves}, indent=1, sort_keys=True) + "\n"
    )
    print(f"{OUT}: {len(states)} states, {len(moves)} moves")


if __name__ == "__main__":
    main()
