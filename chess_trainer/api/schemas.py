"""Request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from chess_trainer.db.cards_repo import CardRow
from chess_trainer.db.games_repo import StoredGame
from chess_trainer.db.schedule_repo import ScheduleRow
from chess_trainer.engine.eval_format import bar_fraction, format_eval
from chess_trainer.engine.eval_types import Eval
from chess_trainer.pgn import positions as positions_module
from chess_trainer.pgn.positions import PositionMove
from chess_trainer.review import my_moves
from chess_trainer.review.browse import browsable_moves
from chess_trainer.review.explain import ExplainedLine, Explanation
from chess_trainer.review.hint import hint_for
from chess_trainer.review.lichess_link import analysis_url
from chess_trainer.review.outcome import my_outcome
from chess_trainer.review.review_job import ReviewJob, ReviewStatus
from chess_trainer.review.review_session import ReviewTarget
from chess_trainer.openings import card_builder, line as line_module
from chess_trainer.openings.card_types import CardMode
from chess_trainer.openings.stats_table import StatsTable
from chess_trainer.review.verdict import ReviewSummary
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


# -- games ---------------------------------------------------------------
class GameOut(BaseModel):
    """A stored game, as the UI needs to describe it."""

    id: str
    url: str | None = None
    my_colour: str
    opponent: str | None = None
    white_username: str | None = None
    black_username: str | None = None
    my_result: str | None = None
    #: ``win`` / ``draw`` / ``loss`` from my side, when the game says.
    my_outcome: str | None = None
    time_class: str | None = None
    end_time: int | None = None
    source: str
    move_count: int | None = None

    @classmethod
    def of(
        cls,
        game: StoredGame,
        *,
        move_count: int | None = None,
        pgn_result: str | None = None,
    ) -> "GameOut":
        return cls(
            id=game.id,
            url=game.url,
            my_colour=game.my_color,
            opponent=game.opponent,
            white_username=game.white_username,
            black_username=game.black_username,
            my_result=game.my_result,
            my_outcome=my_outcome(game.my_result, pgn_result, game.my_color),
            time_class=game.time_class,
            end_time=game.end_time,
            source=game.source,
            move_count=move_count,
        )


class GameResponse(BaseModel):
    game: GameOut


class LatestGameResponse(BaseModel):
    game: GameOut | None = None


class PastePgnRequest(BaseModel):
    pgn: str = Field(min_length=1, description="Full PGN text of the game")


class PollRequest(BaseModel):
    budget_seconds: float | None = Field(
        default=None,
        gt=0,
        le=30,
        description="How long this polling window may take (default ~12s).",
    )


class PollResponse(BaseModel):
    """One polling window. The client repeats these until the ~2 minute budget."""

    found: bool
    game: GameOut | None = None
    attempts: int
    waited: float
    error: str | None = None
    total_budget_seconds: float


# -- review --------------------------------------------------------------
class ReviewTargetOut(BaseModel):
    """The position to solve. The answer itself is deliberately not included."""

    ply: int
    move_number: int
    move_label: str
    fen_before: str
    replay_ucis: list[str]
    mover_is_white: bool
    orientation: str


class ReviewMoveOut(BaseModel):
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
    def of(cls, position: PositionMove, my_colour: str) -> "ReviewMoveOut":
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


class InaccuracyCardAddedOut(BaseModel):
    """The inaccuracy card a finished review made (or brought back)."""

    created: bool
    due_on: str


class HintOut(BaseModel):
    """Which piece the answer moves -- its square and kind, never its destination."""

    square: str
    piece: str
    text: str

    @classmethod
    def of(cls, fen: str, square: str) -> "HintOut":
        hint = hint_for(fen, square)
        return cls(square=hint.square, piece=hint.piece, text=hint.text)


class ReviewSummaryOut(BaseModel):
    found_an_inaccuracy: bool
    move_label: str | None = None
    my_move_san: str | None = None
    my_move_uci: str | None = None
    classification: str | None = None
    best_move_san: str | None = None
    best_move_uci: str | None = None
    eval_before: EvalOut | None = None
    eval_after: EvalOut | None = None
    win_percent_drop: float | None = None
    attempts: int = 0
    used_show_answer: bool = False
    used_hint: bool = False
    solved_first_try: bool = False

    @classmethod
    def of(cls, summary: ReviewSummary) -> "ReviewSummaryOut":
        return cls(
            found_an_inaccuracy=summary.found_an_inaccuracy,
            move_label=summary.move_label,
            my_move_san=summary.my_move_san,
            my_move_uci=summary.my_move_uci,
            classification=summary.classification,
            best_move_san=summary.best_move_san,
            best_move_uci=summary.best_move_uci,
            eval_before=EvalOut.of(summary.eval_before) if summary.eval_before else None,
            eval_after=EvalOut.of(summary.eval_after) if summary.eval_after else None,
            win_percent_drop=summary.win_percent_drop,
            attempts=summary.attempts,
            used_show_answer=summary.used_show_answer,
            used_hint=summary.used_hint,
            solved_first_try=summary.solved_first_try,
        )


class ReviewStateOut(BaseModel):
    """Everything the review view needs, at any point in its lifecycle."""

    step: Step
    status: ReviewStatus
    game: GameOut
    orientation: str
    depth: int
    assessed: int
    total_moves: int
    progress: float
    error: str | None = None
    #: Present once the analysis is done and an inaccuracy was found.
    target: ReviewTargetOut | None = None
    #: True when the game held no inaccuracy at all.
    no_inaccuracy: bool = False
    attempts: int = 0
    used_show_answer: bool = False
    #: Once a hint is taken, the square and piece it pointed at, so coming
    #: back to the review shows it again.
    used_hint: bool = False
    hint: HintOut | None = None
    solved: bool = False
    finished: bool = False
    summary: ReviewSummaryOut | None = None
    #: The moves that can be stepped through: those before my first inaccuracy
    #: while the drill is open, the whole game once the review is over. Empty
    #: while analysing.
    moves: list[ReviewMoveOut] = Field(default_factory=list)
    #: Once the review is over: the game on Lichess's analysis board, opened
    #: at the position before my first inaccuracy, to try moves there.
    lichess_url: str | None = None
    #: Once the review is over: the inaccuracy card made from the slip.
    inaccuracy_card: InaccuracyCardAddedOut | None = None

    @classmethod
    def of(cls, step: Step, job: ReviewJob) -> "ReviewStateOut":
        orientation = job.my_colour
        state = cls(
            step=step,
            status=job.status,
            game=GameOut.of(
                job.game, move_count=job.parsed.move_count, pgn_result=job.parsed.result
            ),
            orientation=orientation,
            depth=job.depth,
            assessed=job.assessed,
            total_moves=job.total_moves,
            progress=job.progress_fraction,
            error=job.error,
        )
        session = job.session
        if session is None:
            return state

        target = session.target
        state.attempts = session.attempt_count
        state.used_show_answer = session.used_show_answer
        state.used_hint = session.used_hint
        if session.used_hint and target is not None:
            state.hint = HintOut.of(target.fen_before, target.best_move_uci[:2])
        state.solved = session.solved
        state.finished = session.finished
        state.no_inaccuracy = target is None
        if target is not None and not session.finished:
            state.target = _target_out(target, orientation)
        if session.finished:
            state.summary = ReviewSummaryOut.of(session.summary())
            if target is not None:
                state.target = _target_out(target, orientation)
        positions = positions_module.from_parsed(job.parsed)
        state.moves = [
            ReviewMoveOut.of(position, job.my_colour)
            for position in browsable_moves(
                positions,
                target_ply=target.ply if target is not None else None,
                finished=session.finished,
            )
        ]
        if session.card_due_on is not None:
            state.inaccuracy_card = InaccuracyCardAddedOut(
                created=session.card_created, due_on=session.card_due_on.isoformat()
            )
        if session.finished:
            state.lichess_url = analysis_url(
                positions,
                start_fen=job.parsed.start_fen,
                ply=target.ply if target is not None else 0,
                my_colour=job.my_colour,
            )
        return state


def _target_out(target: ReviewTarget, orientation: str) -> ReviewTargetOut:
    return ReviewTargetOut(
        ply=target.ply,
        move_number=target.move_number,
        move_label=target.move_label,
        fen_before=target.fen_before,
        replay_ucis=list(target.replay_ucis),
        mover_is_white=target.mover_is_white,
        orientation=orientation,
    )


class StartReviewRequest(BaseModel):
    step: Step
    #: Omit to review the most recent stored game.
    game_id: str | None = None
    #: Re-analyse from scratch rather than resuming an in-progress review.
    restart: bool = False


class AttemptRequest(BaseModel):
    step: Step
    from_square: str = Field(alias="from", min_length=2, max_length=2)
    to_square: str = Field(alias="to", min_length=2, max_length=2)
    promotion: str | None = None

    model_config = {"populate_by_name": True}


class AttemptResponse(BaseModel):
    correct: bool
    uci: str
    san: str
    #: Evaluation of the position after the attempted move, for the eval bar.
    evaluation: EvalOut
    fen_after: str
    attempts: int
    review: ReviewStateOut
    session: SessionOut | None = None
    streak: StreakOut | None = None


class AcknowledgeResponse(BaseModel):
    """Returned when closing a review that had nothing to solve."""

    review: ReviewStateOut
    session: SessionOut | None = None
    streak: StreakOut | None = None


class ShowAnswerRequest(BaseModel):
    step: Step


class ShowAnswerResponse(BaseModel):
    best_move_uci: str
    best_move_san: str
    fen_after: str
    evaluation: EvalOut
    review: ReviewStateOut
    session: SessionOut | None = None
    streak: StreakOut | None = None


class HintResponse(BaseModel):
    hint: HintOut
    review: ReviewStateOut


class LineMoveOut(BaseModel):
    uci: str
    san: str
    label: str
    fen_after: str
    mover_is_white: bool


class ExplainedLineOut(BaseModel):
    moves: list[LineMoveOut]
    evaluation: EvalOut
    notes: list[str]

    @classmethod
    def of(cls, line: ExplainedLine) -> "ExplainedLineOut":
        return cls(
            moves=[
                LineMoveOut(
                    uci=m.uci,
                    san=m.san,
                    label=m.label,
                    fen_after=m.fen_after,
                    mover_is_white=m.mover_is_white,
                )
                for m in line.moves
            ],
            evaluation=EvalOut.of(line.evaluation),
            notes=list(line.notes),
        )


class ExplanationResponse(BaseModel):
    """The engine's line after its move, and after mine, read back in words."""

    best: ExplainedLineOut
    mine: ExplainedLineOut

    @classmethod
    def of(cls, explanation: Explanation) -> "ExplanationResponse":
        return cls(
            best=ExplainedLineOut.of(explanation.best),
            mine=ExplainedLineOut.of(explanation.mine),
        )


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
    source: str
    #: Where the slip came from, for the prompt.
    opponent: str | None = None
    played_on: int | None = None
    interval_days: int | None = None
    reps: int = 0


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
