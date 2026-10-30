"""Why the engine's move is the answer, and what was wrong with mine.

There is no understanding here, only the engine's own lines read back in
words. After the review it shows two lines from the position where I went
wrong:

* **the best line** -- the engine's move, then its continuation;
* **my line** -- the move I played, then the engine's punishing reply and what
  follows.

Each comes with plain facts that can be read straight off the moves: what the
first move captures or checks, what the reply to my move does, the evaluation
(or a forced mate), and the material each side picks up along the line. Seeing
"…Qh4+ captures your pawn on e4 — over this line you lose a pawn" next to the
moves is usually the reason.

A line is cut after :data:`MAX_PLIES`, but never in the middle of an exchange
or a run of checks: material counted half-way through a trade is a lie.

Pure: positions and UCI lines in, words out.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import chess

from chess_trainer.engine.eval_format import format_eval
from chess_trainer.engine.eval_types import Eval

#: Plies shown before a line is cut (extended while it is still trading).
MAX_PLIES = 10

#: Ordinary piece values, for "who came out ahead".
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}

_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


@dataclass(frozen=True, slots=True)
class LineMove:
    uci: str
    san: str
    #: As written in a score: ``2.Bc4`` or ``2...Nf6``.
    label: str
    fen_after: str
    mover_is_white: bool


@dataclass(frozen=True, slots=True)
class ExplainedLine:
    moves: tuple[LineMove, ...]
    #: The engine's evaluation after the line's first move, White's view.
    evaluation: Eval
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Explanation:
    best: ExplainedLine
    mine: ExplainedLine


# -- reading a line --------------------------------------------------------
def legal_prefix(fen: str, ucis: Sequence[str]) -> list[chess.Move]:
    """The moves of ``ucis`` that can actually be played, in order."""
    board = chess.Board(fen)
    moves: list[chess.Move] = []
    for uci in ucis:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        moves.append(move)
        board.push(move)
    return moves


def trim(fen: str, ucis: Sequence[str], max_plies: int = MAX_PLIES) -> list[str]:
    """Cut a line to ``max_plies``, carrying on while it is capturing or checking.

    Never more than twice ``max_plies``, so a long run of checks still ends.
    """
    board = chess.Board(fen)
    kept: list[str] = []
    for move in legal_prefix(fen, ucis):
        if len(kept) >= 2 * max_plies:
            break
        if len(kept) >= max_plies and not _last_was_forcing(board):
            break
        kept.append(move.uci())
        board.push(move)
    return kept


def _last_was_forcing(board: chess.Board) -> bool:
    """Whether the move that led to ``board`` was a capture or a check."""
    if not board.move_stack:
        return False
    if board.is_check():
        return True
    last = board.pop()
    try:
        return board.is_capture(last)
    finally:
        board.push(last)


def line_moves(fen: str, ucis: Sequence[str]) -> tuple[LineMove, ...]:
    """Each move with its SAN, its label and the position after it."""
    board = chess.Board(fen)
    out: list[LineMove] = []
    for move in legal_prefix(fen, ucis):
        white = board.turn == chess.WHITE
        number = board.fullmove_number
        san = board.san(move)
        board.push(move)
        out.append(
            LineMove(
                uci=move.uci(),
                san=san,
                label=f"{number}{'.' if white else '...'}{san}",
                fen_after=board.fen(),
                mover_is_white=white,
            )
        )
    return tuple(out)


def captures(fen: str, ucis: Sequence[str], *, me_white: bool) -> tuple[list[int], list[int]]:
    """Piece types I capture and piece types captured from me, along a line."""
    board = chess.Board(fen)
    mine: list[int] = []
    theirs: list[int] = []
    for move in legal_prefix(fen, ucis):
        taken = _captured_piece(board, move)
        if taken is not None:
            (mine if (board.turn == chess.WHITE) == me_white else theirs).append(taken)
        board.push(move)
    return mine, theirs


def _captured_piece(board: chess.Board, move: chess.Move) -> int | None:
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return chess.PAWN
    piece = board.piece_at(move.to_square)
    return piece.piece_type if piece is not None else None


# -- words -----------------------------------------------------------------
def move_facts(fen: str, uci: str) -> list[str]:
    """What a single move visibly does: capture, check, promote, castle, mate."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    facts: list[str] = []
    if board.is_castling(move):
        facts.append("castles")
    taken = _captured_piece(board, move)
    if taken is not None:
        facts.append(
            f"captures the {chess.piece_name(taken)} on {chess.square_name(move.to_square)}"
        )
    if move.promotion:
        facts.append(f"promotes to a {chess.piece_name(move.promotion)}")
    board.push(move)
    if board.is_checkmate():
        facts.append("is checkmate")
    elif board.is_check():
        facts.append("gives check")
    return facts


def pieces_phrase(piece_types: Sequence[int]) -> str:
    """``[KNIGHT, PAWN, PAWN]`` -> ``a knight and two pawns``."""
    counts = Counter(piece_types)
    parts = []
    for piece_type in sorted(counts, key=lambda t: -PIECE_VALUES.get(t, 0)):
        n = counts[piece_type]
        name = chess.piece_name(piece_type)
        parts.append(f"a {name}" if n == 1 else f"{_NUMBER_WORDS.get(n, str(n))} {name}s")
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def material_note(won: Sequence[int], lost: Sequence[int]) -> str | None:
    """A sentence on what each side picks up over the line, or None if nothing."""
    if not won and not lost:
        return None
    net = sum(PIECE_VALUES.get(t, 0) for t in won) - sum(PIECE_VALUES.get(t, 0) for t in lost)
    if not lost:
        return f"Over this line you win {pieces_phrase(won)}."
    if not won:
        return f"Over this line you lose {pieces_phrase(lost)}."
    balance = "an even trade" if net == 0 else f"net {net:+d}"
    return f"Over this line you win {pieces_phrase(won)} and give up {pieces_phrase(lost)} — {balance}."


def _mate_for(evaluation: Eval, me_white: bool) -> int | None:
    """Mate distance from my side's view: positive if I mate, negative if mated."""
    pov = evaluation.pov(me_white)
    return pov.mate


def _sentence(subject: str, facts: list[str]) -> str:
    if len(facts) > 1:
        return f"{subject} {', '.join(facts[:-1])} and {facts[-1]}."
    return f"{subject} {facts[0]}."


# -- the explanation -------------------------------------------------------
def explain_best(
    fen_before: str,
    best_uci: str,
    reply_pv: Sequence[str],
    evaluation: Eval,
) -> ExplainedLine:
    """The engine's move and its continuation (``reply_pv`` is from the position after it)."""
    me_white = chess.Board(fen_before).turn == chess.WHITE
    line = trim(fen_before, [best_uci, *reply_pv])
    moves = line_moves(fen_before, line)
    notes: list[str] = []

    facts = move_facts(fen_before, best_uci)
    if facts:
        notes.append(_sentence(moves[0].san, facts))

    mate = _mate_for(evaluation, me_white)
    if mate is not None and mate > 0:
        notes.append(f"It forces mate in {mate}.")
    else:
        notes.append(f"After it the engine rates the position {format_eval(evaluation)}.")

    won, lost = captures(fen_before, line, me_white=me_white)
    if (material := material_note(won, lost)) is not None:
        notes.append(material)
    return ExplainedLine(moves=moves, evaluation=evaluation, notes=tuple(notes))


def explain(
    fen_before: str,
    *,
    best_uci: str,
    best_reply_pv: Sequence[str],
    best_eval: Eval,
    my_uci: str,
    my_reply_pv: Sequence[str],
    eval_before: Eval,
    eval_after: Eval,
    win_percent_drop: float | None,
) -> Explanation:
    """Both lines from the position where I went wrong."""
    return Explanation(
        best=explain_best(fen_before, best_uci, best_reply_pv, best_eval),
        mine=explain_mine(
            fen_before,
            my_uci,
            my_reply_pv,
            eval_before=eval_before,
            eval_after=eval_after,
            win_percent_drop=win_percent_drop,
        ),
    )


def explain_mine(
    fen_before: str,
    my_uci: str,
    reply_pv: Sequence[str],
    *,
    eval_before: Eval,
    eval_after: Eval,
    win_percent_drop: float | None,
) -> ExplainedLine:
    """The move I played and how the engine answers it."""
    board = chess.Board(fen_before)
    me_white = board.turn == chess.WHITE
    line = trim(fen_before, [my_uci, *reply_pv])
    moves = line_moves(fen_before, line)
    notes: list[str] = []

    facts = move_facts(fen_before, my_uci)
    if facts:
        notes.append(_sentence(moves[0].san, facts))

    if len(moves) > 1:
        board.push(chess.Move.from_uci(my_uci))
        reply = moves[1]
        reply_facts = [
            fact.replace("captures the ", "captures your ") for fact in move_facts(board.fen(), reply.uci)
        ]
        if reply_facts:
            notes.append(_sentence(f"The engine answers {reply.label}, which", reply_facts))
        else:
            notes.append(f"The engine answers {reply.label}.")

    mate = _mate_for(eval_after, me_white)
    swing = f"{format_eval(eval_before)} → {format_eval(eval_after)}"
    if mate is not None and mate < 0:
        notes.append(f"It allows mate in {-mate} ({swing}).")
    elif win_percent_drop is not None:
        notes.append(f"It costs {win_percent_drop:.1f}% of your winning chances ({swing}).")
    else:
        notes.append(f"The evaluation goes {swing}.")

    won, lost = captures(fen_before, line, me_white=me_white)
    if (material := material_note(won, lost)) is not None:
        notes.append(material)
    return ExplainedLine(moves=moves, evaluation=eval_after, notes=tuple(notes))
