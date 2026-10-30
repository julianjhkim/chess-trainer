"""A link that opens a reviewed game on Lichess's analysis board.

The review shows the engine's lines but is no place to try moves of your own;
Lichess's analysis board is. Its URL can carry a whole game, so the link is
built here and nothing is sent anywhere until it is clicked:

    https://lichess.org/analysis/pgn/1.e4%20e5%202.Nf3?color=black#2

``#n`` opens the game after ``n`` plies -- the position before my first
inaccuracy -- and ``color`` puts my side at the bottom. Only the moves go in
the URL, no names or other headers.

A game that did not start from the usual position cannot be passed as moves,
so it links to the analysis board at the position itself instead.

Pure: positions in, a URL out.
"""

from __future__ import annotations

from urllib.parse import quote

import chess

from chess_trainer.pgn.positions import PositionMove

ANALYSIS_URL = "https://lichess.org/analysis"


def movetext(positions: list[PositionMove]) -> str:
    """``1.e4 e5 2.Nf3``, with ``1...e5`` style numbering if Black moves first."""
    parts: list[str] = []
    for index, position in enumerate(positions):
        if position.mover_is_white:
            parts.append(f"{position.move_number}.{position.san}")
        elif index == 0:
            parts.append(f"{position.move_number}...{position.san}")
        else:
            parts.append(position.san)
    return " ".join(parts)


def analysis_url(
    positions: list[PositionMove],
    *,
    start_fen: str,
    ply: int,
    my_colour: str,
) -> str:
    """The Lichess analysis board for this game, opened after ``ply`` plies."""
    colour = "black" if my_colour == "black" else "white"
    if start_fen != chess.STARTING_FEN or not positions:
        fen = positions[ply].fen_before if 0 <= ply < len(positions) else start_fen
        return f"{ANALYSIS_URL}/{quote(fen.replace(' ', '_'), safe='/_')}?color={colour}"
    # `#`, `+` and `=` all occur in SAN and would break a URL, so everything but
    # the move-number dots is escaped.
    ply = max(0, min(ply, len(positions)))
    return f"{ANALYSIS_URL}/pgn/{quote(movetext(positions), safe='.')}?color={colour}#{ply}"
