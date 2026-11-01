"""Request and response models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.engine.eval_format import bar_fraction, format_eval
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn.positions import PositionMove
from chess_trainer.pgn import my_moves
from chess_trainer.inaccuracies.hint import hint_for
from chess_trainer.openings import card_builder, line as line_module
from chess_trainer.openings.card_types import CardMode
from chess_trainer.openings.stats_table import StatsTable
from chess_trainer.srs.due import CardSource
from chess_trainer.srs.scheduler import AnswerOutcome, QueueCounts
from chess_trainer.session.flow import SessionFlow
from chess_trainer.session.steps import Step
from chess_trainer.streak.streak import Streak

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# -- evaluation ----------------------------------------------------------
class EvalOut(BaseModel):
    """An evaluation, ready for the eval bar. Always White's perspective."""

    cp: int | None = None
    mate: int | None = None
    text: str
    fraction: float = Field(description="Share of the bar filled by White, 0..1")

    @classmethod
    def of(cls, evaluation: Eval) -> "EvalOut":
        return cls(
            cp=evaluation.cp,
            mate=evaluation.mate,
            text=format_eval(evaluation),
            fraction=bar_fraction(evaluation),
        )


class EvalRequest(BaseModel):
    fen: str = Field(default=START_FEN, description="Position to evaluate")
    depth: int | None = Field(default=None, ge=1, le=40)


class EvalResponse(BaseModel):
    fen: str
    depth: int
    evaluation: EvalOut
    best_move: str | None = None
    cached: bool = False


# -- session -------------------------------------------------------------
class StepOut(BaseModel):
    step: Step
    position: int
    title: str
    enabled: bool
    completed: bool
    current: bool


class SessionOut(BaseModel):
    started: bool
    current: Step | None
    finished: bool
    steps: list[StepOut]

    @classmethod
    def of(cls, flow: SessionFlow) -> "SessionOut":
        return cls(
            started=flow.started,
            current=flow.current,
            finished=flow.is_finished,
            steps=[
                StepOut(
                    step=i.step,
                    position=i.position,
                    title=i.title,
                    enabled=i.enabled,
                    completed=i.completed,
                    current=i.current,
                )
                for i in flow.step_bar()
            ],
        )


class StartSessionRequest(BaseModel):
    steps: list[Step] | None = Field(
        default=None,
        description="Steps to run; omit or send null for all four.",
    )
    start_at: Step | None = Field(
        default=None,
        description="Begin at this step rather than the first one.",
    )


# -- streak --------------------------------------------------------------
class StreakOut(BaseModel):
    current: int
    longest: int
    active_today: bool
    total_days: int

    @classmethod
    def of(cls, streak: Streak) -> "StreakOut":
        return cls(
            current=streak.current,
            longest=streak.longest,
            active_today=streak.active_today,
            total_days=streak.total_days,
        )


class SessionAndStreakOut(BaseModel):
    """Returned when completing a step, which can move the streak."""

    session: SessionOut
    streak: StreakOut


# -- health --------------------------------------------------------------
class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    engine: dict[str, object]
    database: str
    chesscom_username: str
    lichess_token_present: bool
    timezone: str


# -- moves and hints ---------------------------------------------------
class GameMoveOut(BaseModel):
    """One move of the game, for stepping through it with the arrow keys."""

    ply: int
    move_number: int
    label: str
    san: str
    uci: str
    fen_before: str
    fen_after: str
    mover_is_white: bool
    is_mine: bool

    @classmethod
    def of(cls, position: PositionMove, my_colour: str) -> "GameMoveOut":
        return cls(
            ply=position.ply,
            move_number=position.move_number,
            label=position.move_label,
            san=position.san,
            uci=position.uci,
            fen_before=position.fen_before,
            fen_after=position.fen_after,
            mover_is_white=position.mover_is_white,
            is_mine=my_moves.is_mine(position, my_colour),
        )


class HintOut(BaseModel):
    """Which piece the answer moves -- its square and kind, never its destination."""

    square: str
    piece: str
    text: str

    @classmethod
    def of(cls, fen: str, square: str) -> "HintOut":
        hint = hint_for(fen, square)
        return cls(square=hint.square, piece=hint.piece, text=hint.text)


# -- opening cards -------------------------------------------------------
class QueueCountsOut(BaseModel):
    due: int
    new: int
    relearning: int

    @classmethod
    def of(cls, counts: QueueCounts) -> "QueueCountsOut":
        return cls(due=counts.due, new=counts.new, relearning=counts.relearning)


class CardScheduleOut(BaseModel):
    n: int
    ef: float
    interval_days: int
    due_on: str
    reps: int
    lapses: int

    @classmethod
    def of(cls, schedule: ScheduleRow) -> "CardScheduleOut":
        return cls(
            n=schedule.n,
            ef=round(schedule.ef, 3),
            interval_days=schedule.interval_days,
            due_on=schedule.due_on.isoformat(),
            reps=schedule.reps,
            lapses=schedule.lapses,
        )


class CardOut(BaseModel):
    """A card to drill. The answer is deliberately absent."""

    id: int
    line_uci: str
    line_label: str
    depth: int
    #: Whose move I have to find.
    side_to_move: str
    #: Moves auto-played before the given move.
    replay_ucis: list[str]
    #: The branch move, shown as an arrow for me to play.
    given_move_uci: str
    given_move_san: str
    #: Position before the given move, i.e. where the arrow is drawn.
    fen_before_given: str
    #: Position after the given move: the one whose answer I must find.
    fen: str
    #: Revealed once I have played the given move.
    opening_eco: str | None = None
    opening_name: str | None = None
    opening_label: str | None = None
    mode: str | None = None
    position_games: int
    #: Whether the most played move is also Stockfish's top move at the
    #: configured depth. Only frequency cards have anything to compare, so
    #: ``None`` means "nothing to say" -- never "no". Deliberately a bare
    #: yes/no: naming either move would give the answer away.
    engine_agrees: bool | None = None
    source: CardSource
    schedule: CardScheduleOut | None = None

    @classmethod
    def of(
        cls,
        card: CardRow,
        *,
        source: CardSource,
        schedule: ScheduleRow | None = None,
        engine_best_uci: str | None = None,
    ) -> "CardOut":
        ucis = card.ucis
        before = line_module.position_of(ucis[:-1])
        return cls(
            id=card.id or 0,
            line_uci=card.line_uci,
            line_label=line_module.line_label(ucis),
            depth=card.depth,
            side_to_move=card.side_to_move,
            replay_ucis=list(ucis[:-1]),
            given_move_uci=card.given_move_uci,
            given_move_san=card.given_move_san,
            fen_before_given=before.fen,
            fen=card.fen,
            opening_eco=card.opening_eco,
            opening_name=card.opening_name,
            opening_label=card.opening_label,
            mode=card.mode,
            position_games=card.position_games,
            engine_agrees=card_builder.engine_agrees(card, engine_best_uci),
            source=source,
            schedule=CardScheduleOut.of(schedule) if schedule else None,
        )


class CardStateOut(BaseModel):
    """The current card, if any, plus what is waiting behind it."""

    card: CardOut | None = None
    counts: QueueCountsOut
    attempts: int = 0
    used_show_answer: bool = False
    solved: bool = False
    finished: bool = False
    #: Set when the tree has nothing left to serve.
    exhausted: bool = False


class StatsRowOut(BaseModel):
    san: str
    uci: str
    games: int
    share: float
    white: int
    draws: int
    black: int
    white_percent: float
    draw_percent: float
    black_percent: float
    average_rating: int | None = None
    is_answer: bool = False
    is_engine_move: bool = False
    is_most_played: bool = False
    is_tied: bool = False


class StatsTableOut(BaseModel):
    rows: list[StatsRowOut]
    total_games: int
    mode: str | None = None
    tie_note: str | None = None
    engine_note: str | None = None

    @classmethod
    def of(cls, table: StatsTable) -> "StatsTableOut":
        return cls(
            rows=[
                StatsRowOut(
                    san=r.san,
                    uci=r.uci,
                    games=r.games,
                    share=round(r.share, 2),
                    white=r.white,
                    draws=r.draws,
                    black=r.black,
                    white_percent=round(r.white_percent, 1),
                    draw_percent=round(r.draw_percent, 1),
                    black_percent=round(r.black_percent, 1),
                    average_rating=r.average_rating,
                    is_answer=r.is_answer,
                    is_engine_move=r.is_engine_move,
                    is_most_played=r.is_most_played,
                    is_tied=r.is_tied,
                )
                for r in table.rows
            ],
            total_games=table.total_games,
            mode=table.mode.value if table.mode else None,
            tie_note=table.tie_note,
            engine_note=table.engine_note,
        )


class DeadEndOut(BaseModel):
    """A branch that stops because the position has too few master games."""

    line_label: str
    given_move_san: str
    games: int
    white: int = 0
    draws: int = 0
    black: int = 0
    average_rating: int | None = None
    message: str = "Max depth reached"
    detail: str | None = None


class CardGradeOut(BaseModel):
    quality: int
    description: str
    passed: bool
    was_new: bool
    rescheduled: bool
    requeued: bool
    interval_days: int | None = None
    due_on: str | None = None
    ef: float | None = None

    @classmethod
    def of(cls, outcome: AnswerOutcome) -> "CardGradeOut":
        from chess_trainer.srs import grading

        return cls(
            quality=outcome.quality,
            description=grading.describe(outcome.quality, outcome.attempts),
            passed=outcome.passed,
            was_new=outcome.was_new,
            rescheduled=outcome.rescheduled,
            requeued=outcome.requeued,
            interval_days=outcome.interval_days,
            due_on=outcome.due_on.isoformat() if outcome.due_on else None,
            ef=round(outcome.ef, 3) if outcome.ef is not None else None,
        )


class CardAttemptRequest(BaseModel):
    from_square: str = Field(alias="from", min_length=2, max_length=2)
    to_square: str = Field(alias="to", min_length=2, max_length=2)
    promotion: str | None = None

    model_config = {"populate_by_name": True}


class CardAttemptResponse(BaseModel):
    correct: bool
    uci: str
    san: str
    #: Evaluation after the attempted move, for the eval bar.
    evaluation: EvalOut
    fen_after: str
    attempts: int
    finished: bool
    #: Everything below is present only once the card is finished.
    answer_uci: str | None = None
    answer_san: str | None = None
    stats: StatsTableOut | None = None
    grade: CardGradeOut | None = None
    dead_ends: list[DeadEndOut] = Field(default_factory=list)
    branches_created: int = 0
    counts: QueueCountsOut | None = None
    session: SessionOut | None = None
    streak: StreakOut | None = None


class ShowCardAnswerResponse(BaseModel):
    answer_uci: str
    answer_san: str
    fen_after: str
    evaluation: EvalOut
    attempts: int
    stats: StatsTableOut
    grade: CardGradeOut
    dead_ends: list[DeadEndOut] = Field(default_factory=list)
    branches_created: int = 0
    counts: QueueCountsOut
    session: SessionOut | None = None
    streak: StreakOut | None = None


# -- inaccuracy cards ----------------------------------------------------
class InaccuracyCountsOut(BaseModel):
    due: int
    relearning: int
    total: int
    #: When the next card is due, if none is due now.
    next_due_on: str | None = None


class InaccuracyCardOut(BaseModel):
    """A position to solve. The answer and the move I played stay server-side."""

    id: int
    fen: str
    orientation: str
    #: The move that led here, highlighted on the board.
    last_move_uci: str | None = None
    move_number: int
    classification: str
    #: What I played here in the game, shown while solving (not the answer).
    my_move_uci: str
    my_move_san: str
    move_label: str
    source: str
    #: Where the slip came from, for the prompt.
    opponent: str | None = None
    played_on: int | None = None
    interval_days: int | None = None
    reps: int = 0
    #: The game's moves before the slip, to step through while solving. Empty
    #: when the game is not stored.
    moves: list[GameMoveOut] = Field(default_factory=list)


class InaccuracyGradeOut(BaseModel):
    quality: int
    description: str
    passed: bool
    requeued: bool
    interval_days: int | None = None
    due_on: str | None = None
    ef: float | None = None


class InaccuracyResultOut(BaseModel):
    """The report once a card is answered: the answer, my game move, the grade."""

    answer_uci: str
    answer_san: str
    my_move_uci: str
    my_move_san: str
    move_label: str
    classification: str
    win_percent_drop: float | None = None
    revealed: bool = False
    grade: InaccuracyGradeOut
    #: The whole game, to step through once the card is answered; the slip is
    #: move ``ply`` (0-based), so position ``ply`` is the card's position.
    moves: list[GameMoveOut] = Field(default_factory=list)
    ply: int = 0
    #: The game on Lichess's analysis board, opened at the card's position
    #: (just the position when the game is not stored). Only once answered:
    #: Lichess's engine would give the answer away.
    lichess_url: str | None = None


class InaccuracyStateOut(BaseModel):
    card: InaccuracyCardOut | None = None
    counts: InaccuracyCountsOut
    attempts: int = 0
    hint: HintOut | None = None
    finished: bool = False
    result: InaccuracyResultOut | None = None
    #: True when /next found nothing left to drill.
    exhausted: bool = False


class InaccuracyAttemptResponse(BaseModel):
    correct: bool
    uci: str
    san: str
    evaluation: EvalOut
    fen_after: str
    attempts: int
    finished: bool
    result: InaccuracyResultOut | None = None
    counts: InaccuracyCountsOut | None = None
    session: SessionOut | None = None
    streak: StreakOut | None = None


class NewCardRequest(BaseModel):
    """A card to make: a game, and the number of my move that went wrong."""

    pgn: str = Field(min_length=1, description="Full PGN text of the game")
    move_number: int = Field(ge=1, description="My move's number in the game score")
    #: Which side I had; None reads it from the PGN's player names.
    colour: Literal["white", "black"] | None = None


class NewCardPreviewOut(BaseModel):
    """The position a card would drill, before anything is saved."""

    colour: str
    move_number: int
    ply: int
    move_label: str
    my_move_uci: str
    my_move_san: str
    fen: str
    last_move_uci: str | None = None
    opponent: str | None = None
    #: The moves before the slip, to step through.
    moves: list[GameMoveOut] = Field(default_factory=list)
    #: "none", "active" (the position already has a card) or "deleted".
    existing: str = "none"


class NewCardOut(BaseModel):
    """A card made: never the answer, only when it is due."""

    move_label: str
    due_on: str
    created: bool
    restored: bool = False
    counts: InaccuracyCountsOut
