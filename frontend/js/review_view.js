/**
 * The game review (steps 1 and 3).
 *
 * Lifecycle:
 *   no game        -> offer a chess.com fetch, with a PGN paste fallback
 *   analysing      -> poll for progress (depth-20 analysis takes a while)
 *   no inaccuracy  -> say so, and let the step be closed
 *   target ready   -> auto-replay to the position, then I play the move
 *   solved/revealed-> show the summary; the review is over
 *
 * The board is oriented to the colour I played. The eval bar refreshes after
 * every attempt, including wrong ones, so each try's cost is visible.
 *
 * Once the board is up, ← / → step through the game (Home / End jump). While
 * the drill is open that covers the moves leading to the position, and the
 * board only takes a move back at the live position; once the review is over
 * it covers the whole game, with the engine's answer sitting beside the move I
 * actually played.
 *
 * *Hint* circles the piece the answer moves (the server sends only its square).
 * Once the review is over, a "Why" card reads back the engine's line after its
 * move and after mine; clicking a move in either line shows it on the board.
 */

import * as api from './api.js';
import { createPause, createReplay, replayDelayFor } from './animate.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { renderExplanation } from './explanation_view.js';
import { createMoveList } from './move_list.js';
import { bindArrowKeys, createMoveNav } from './move_nav.js';
import { createPgnPaste } from './pgn_paste.js';
import { get, set, setStatus, withStatus } from './state.js';

const POLL_INTERVAL_MS = 700;
const WRONG_MOVE_LINGER_MS = 1100;
/** Holding an arrow key down steps quickly; only evaluate where it stops. */
const EVAL_DEBOUNCE_MS = 180;

const CLASSIFICATION_LABEL = {
  inaccuracy: 'an inaccuracy',
  mistake: 'a mistake',
  blunder: 'a blunder',
};

export function renderReviewView(container, { step, onCompleted }) {
  container.replaceChildren();

  let destroyed = false;
  let pollTimer = null;
  let replay = null;
  let pause = null;
  let board = null;
  let review = null;
  const attemptLog = [];
  /** Whether the arrow keys may move the board (not mid-replay or mid-attempt). */
  let navReady = false;
  let latestView = null;
  let drawing = Promise.resolve();
  let evalTimer = null;
  let evalToken = 0;
  /** The hint taken for this position (`{square, piece, text}`), if any. */
  let hint = null;
  let hintLine = null;
  let explainToken = 0;

  // -- layout ------------------------------------------------------------
  const layout = document.createElement('div');
  layout.className = 'board-layout';

  const boardColumn = document.createElement('div');
  boardColumn.className = 'board-column';

  const boardAndBar = document.createElement('div');
  boardAndBar.className = 'board-and-bar';

  const evalBar = createEvalBar();
  const controls = document.createElement('div');
  controls.className = 'button-row';

  const navRow = document.createElement('div');
  navRow.className = 'button-row nav-row';
  navRow.hidden = true;

  boardColumn.append(boardAndBar, navRow, controls);

  const side = document.createElement('div');
  side.className = 'side-panel';

  layout.append(boardColumn, side);
  container.append(layout);

  // -- side panel cards --------------------------------------------------
  const gameCard = card('Game', panelChanged);
  const promptCard = card(step.title, panelChanged);
  const lichessCard = card('Review at Lichess', panelChanged);
  const whyCard = card('Why', panelChanged);
  const movesCard = card('Moves', panelChanged);
  const attemptsCard = card('Attempts', panelChanged);
  side.append(gameCard.root, promptCard.root, movesCard.root);
  // Under the buttons, beside the moves they are about: the attempts while
  // solving, and once it is over the "why" above them.
  boardColumn.append(lichessCard.root, whyCard.root, attemptsCard.root);
  lichessCard.root.hidden = true;
  whyCard.root.hidden = true;
  movesCard.root.hidden = true;
  attemptsCard.root.hidden = true;

  // -- move navigation ---------------------------------------------------
  const nav = createMoveNav({ onChange: onNavChange });
  const moveList = createMoveList({
    onSelect: (index) => {
      if (navReady) nav.go(index);
    },
  });
  movesCard.setBody(moveList.element);
  navRow.append(
    navButton('⏮', 'Start (Home)', () => nav.first()),
    navButton('◀', 'Previous move (←)', () => nav.back()),
    navButton('▶', 'Next move (→)', () => nav.forward()),
    navButton('⏭', 'End (End)', () => nav.last()),
  );
  const unbindKeys = bindArrowKeys(nav, { enabled: () => navReady && !destroyed });

  // -- boot --------------------------------------------------------------
  start();

  async function start() {
    promptCard.setBody(paragraph('Looking for a game to review…', 'choice-note'));
    try {
      // A game handed over by the play step (a pasted PGN) is reviewed by id:
      // `latest` orders by when a game was played, so an undated paste would
      // otherwise lose to an older game that happens to carry a date.
      const handedOver = get().pendingGameId;
      if (handedOver) set({ pendingGameId: null });
      review = await api.startReview(step.step, { gameId: handedOver ?? null });
      onReviewState();
    } catch (error) {
      if (/No game to review/i.test(error.message)) {
        renderNeedsGame();
      } else {
        renderError(error.message);
      }
    }
  }

  // -- states ------------------------------------------------------------
  function renderNeedsGame() {
    gameCard.setBody(paragraph('No game stored yet.', 'choice-note'));
    const body = document.createElement('div');
    body.append(
      paragraph(
        step.step === 'review_new_game'
          ? 'Nothing to review yet. Fetch your latest game from chess.com, or paste its PGN.'
          : 'Fetch your most recent chess.com game to review it.',
        'choice-note',
      ),
    );

    const row = document.createElement('div');
    row.className = 'button-row';
    const fetchButton = button('Fetch my latest game', async () => {
      await withStatus('Asking chess.com…', async () => {
        await api.fetchLatestGame();
      });
      await start();
    }, 'primary');
    row.append(fetchButton);
    body.append(row, pgnPasteWidget().element);
    promptCard.setBody(body);
  }

  function renderError(message) {
    promptCard.setBody(paragraph(message, 'paste-error'));
    setStatus(message, 'error');
  }

  function onReviewState() {
    if (destroyed) return;
    renderGameCard();
    hint = review.hint ?? null;

    if (review.status === 'failed') {
      renderError(review.error || 'The review failed.');
      return;
    }
    if (review.status === 'analysing') {
      hideNav();
      renderAnalysing();
      schedulePoll();
      return;
    }
    stopPolling();

    if (review.finished) {
      void renderFinished();
      return;
    }
    if (review.no_inaccuracy) {
      renderNoInaccuracy();
      return;
    }
    renderTarget();
  }

  function renderGameCard() {
    const game = review?.game;
    if (!game) return;
    const list = document.createElement('dl');
    list.className = 'kv';
    const opponent = game.opponent ?? 'unknown';
    addRow(list, 'Opponent', opponent);
    addRow(list, 'I played', game.my_colour);
    if (game.my_result) addRow(list, 'Result', game.my_result.replace(/_/g, ' '));
    if (game.move_count) addRow(list, 'Moves', String(game.move_count));
    if (game.time_class) addRow(list, 'Type', game.time_class);

    // The link goes inside the body, which `setBody` replaces: this runs on
    // every progress poll, and anything appended to the card itself would
    // pile up one more link per poll.
    const body = document.createElement('div');
    body.append(list);
    if (game.url) {
      const link = document.createElement('a');
      link.href = game.url;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      link.textContent = 'Open on chess.com ↗';
      link.className = 'choice-note';
      body.append(link);
    }
    gameCard.setBody(body);
  }

  function renderAnalysing() {
    const body = document.createElement('div');
    body.append(
      paragraph(
        `Analysing your moves at depth ${review.depth}. Only your moves are checked, and it stops at your first inaccuracy.`,
        'choice-note',
      ),
    );

    const bar = document.createElement('div');
    bar.className = 'progress';
    const fill = document.createElement('div');
    fill.className = 'progress-fill';
    fill.style.width = `${Math.round(review.progress * 100)}%`;
    bar.append(fill);

    const count = document.createElement('p');
    count.className = 'mono';
    count.style.margin = '8px 0 0';
    count.textContent = review.total_moves
      ? `move ${review.assessed} of ${review.total_moves}`
      : 'starting…';

    body.append(bar, count);
    promptCard.setBody(body);
    ensureBoardAtStart();
  }

  function renderNoInaccuracy() {
    const body = document.createElement('div');
    const outcome = review.game?.my_outcome;
    if (outcome === 'win' || outcome === 'draw') {
      // A clean game that also didn't lose deserves more than a shrug.
      const headline = paragraph('Congratulations — a perfect game!', 'perfect-game');
      body.append(
        headline,
        paragraph(
          `You ${outcome === 'win' ? 'won' : 'drew'} without a single inaccuracy: none of your moves lost 10% or more.`,
          '',
        ),
      );
    } else {
      body.append(
        paragraph('No inaccuracy in this game — nothing of yours lost 10% or more. Well played.', ''),
      );
    }
    body.append(
      paragraph(
        `All ${review.total_moves} of your moves were checked at depth ${review.depth}.`,
        'choice-note',
      ),
    );
    const row = document.createElement('div');
    row.className = 'button-row';
    row.append(
      button('Done', async () => {
        const result = await withStatus('Saving…', () => api.reviewAcknowledge(step.step));
        applyCompletion(result);
      }, 'primary'),
    );
    body.append(
      row,
      paragraph('← → step through the game; Home and End jump to either end.', 'choice-note'),
      pgnPasteWidget({ summary: 'Review a different game (paste PGN)' }).element,
    );
    promptCard.setBody(body);
    ensureBoardAtStart();
    showNav(review.moves ?? [], { index: 0 });
    renderLichessLink();
  }

  async function renderTarget() {
    const target = review.target;
    if (!target) return;

    hideWhy();
    const body = document.createElement('div');
    const whose = target.mover_is_white ? 'White' : 'Black';
    hintLine = paragraph('', 'hint-line');
    hintLine.hidden = true;
    body.append(
      paragraph(`Move ${target.move_number}. This is where your game first went wrong, playing ${whose}.`, ''),
      paragraph(
        'Find the move the engine wants — only its top choice counts. Unlimited retries.',
        'choice-note',
      ),
      hintLine,
      paragraph(
        '← → step through the moves that led here; End comes back to the position.',
        'choice-note',
      ),
      // The paste fallback stays available mid-review, so a different game can
      // always be loaded without finishing this one first.
      pgnPasteWidget({ summary: 'Review a different game (paste PGN)' }).element,
    );
    promptCard.setBody(body);
    renderHint();

    buildControls();
    await replayToTarget(target);
  }

  async function replayToTarget(target) {
    navReady = false;
    const orientation = review.orientation;
    const fresh = ensureBoard({ orientation });
    await fresh.setFen(fresh.START_FEN);
    fresh.setInteractive(false);
    fresh.setShapes([]);
    fresh.setHighlights([]);

    setStatus(target.replay_ucis.length ? 'Replaying the game…' : 'Your move.');
    replay = createReplay({
      board: fresh,
      ucis: target.replay_ucis,
      delayMs: replayDelayFor(target.replay_ucis.length),
    });
    const completed = await replay.promise;
    if (destroyed || !completed) return;

    await refreshEval(target.fen_before);
    showNav(review.moves ?? [], { index: target.replay_ucis.length });
    fresh.setHighlights(hintShapes());
    fresh.setInteractive(true);
    fresh.setMoveHandler(handleAttempt);
    setStatus('Your move.');
  }

  function buildControls() {
    controls.replaceChildren();
    controls.append(
      button('Hint', showHint),
      button('Show answer', showAnswer),
      button('Flip board', () => board?.flip()),
      button('Replay again', async () => {
        if (review?.target) await replayToTarget(review.target);
      }),
    );
  }

  // -- attempts ----------------------------------------------------------
  async function handleAttempt(moveResult) {
    const target = review?.target;
    if (!target || destroyed) return;

    board.setInteractive(false);
    navReady = false;
    let response;
    try {
      response = await api.reviewAttempt(
        step.step,
        moveResult.uci.slice(0, 2),
        moveResult.uci.slice(2, 4),
        moveResult.uci.length > 4 ? moveResult.uci[4] : null,
      );
    } catch (error) {
      setStatus(error.message, 'error');
      await board.setFen(target.fen_before);
      board.setInteractive(true);
      navReady = true;
      return;
    }

    evalBar.update(response.evaluation);
    attemptLog.push({ san: response.san, text: response.evaluation.text, correct: response.correct });
    renderAttempts();
    review = response.review;

    if (response.correct) {
      setStatus('Correct.');
      applyCompletion(response);
      void renderFinished({ highlight: response.uci });
      return;
    }

    setStatus(`${response.san} is not it — try again.`);
    pause = createPause(WRONG_MOVE_LINGER_MS);
    const kept = await pause.promise;
    if (destroyed || !kept) return;
    await board.setFen(target.fen_before);
    board.setInteractive(true);
    navReady = true;
  }

  async function showHint() {
    if (!review?.target || review.finished) return;
    const response = await withStatus('Asking for a hint…', () => api.reviewHint(step.step));
    hint = response.hint;
    review = response.review;
    renderHint();
    setStatus(hint.text);
    // The circle belongs on the live position; come back to it if browsing.
    if (nav.atEnd) board?.setHighlights(hintShapes());
    else if (navReady) nav.last();
  }

  function renderHint() {
    if (!hintLine) return;
    hintLine.hidden = !hint;
    hintLine.textContent = hint ? `Hint: ${hint.text}` : '';
    panelChanged();
  }

  /** A circle on the piece the hint names, while the position is still open. */
  function hintShapes() {
    if (!hint || !review?.target || review.finished) return [];
    return [{ orig: hint.square, brush: 'yellow' }];
  }

  async function showAnswer() {
    const target = review?.target;
    if (!target) return;
    board?.setInteractive(false);
    navReady = false;
    const response = await withStatus('Revealing…', () => api.reviewShowAnswer(step.step));
    review = response.review;
    await board.setFen(target.fen_before);
    await board.pushMove(response.best_move_uci);
    evalBar.update(response.evaluation);
    applyCompletion(response);
    void renderFinished({ highlight: response.best_move_uci, revealed: true });
  }

  function renderAttempts() {
    if (!attemptLog.length) {
      attemptsCard.root.hidden = true;
      panelChanged();
      return;
    }
    attemptsCard.root.hidden = false;
    const list = document.createElement('ol');
    list.className = 'attempt-list';
    for (const entry of attemptLog) {
      const item = document.createElement('li');
      item.className = entry.correct ? 'attempt-correct' : 'attempt-wrong';
      const move = document.createElement('span');
      move.className = 'mono';
      move.textContent = entry.san;
      const evaluation = document.createElement('span');
      evaluation.className = 'mono attempt-eval';
      evaluation.textContent = entry.text;
      item.append(move, evaluation);
      list.append(item);
    }
    attemptsCard.setBody(list);
  }

  // -- finished ----------------------------------------------------------
  async function renderFinished({ highlight = null, revealed = false } = {}) {
    const summary = review?.summary;
    board?.setHighlights([]);
    controls.replaceChildren();
    controls.append(button('Flip board', () => board?.flip()));

    if (!summary) return;

    if (!summary.found_an_inaccuracy) {
      renderNoInaccuracy();
      return;
    }

    // Coming back to a finished review (via the step bar) means there is no
    // board yet: rebuild the solved position rather than showing a bare summary.
    const target = review.target;
    if (board === null && target) {
      const fresh = ensureBoard({ orientation: review.orientation });
      fresh.setInteractive(false);
      await fresh.setFen(target.fen_before);
      const answer = highlight ?? summary.best_move_uci;
      if (answer) {
        await fresh.pushMove(answer);
        highlight = answer;
      }
      await refreshEval(fresh.getFen());
    }

    const body = document.createElement('div');
    const headline = document.createElement('p');
    headline.style.margin = '0 0 10px';
    headline.style.fontWeight = '600';
    const withHint = summary.used_hint ? ', with a hint' : '';
    headline.textContent = revealed
      ? 'Answer revealed.'
      : summary.solved_first_try
        ? `Correct, first try${withHint}.`
        : `Correct, after ${summary.attempts} attempts${withHint}.`;
    body.append(headline);

    const list = document.createElement('dl');
    list.className = 'kv';
    addRow(list, 'You played', `${summary.move_label} (${CLASSIFICATION_LABEL[summary.classification] ?? summary.classification})`);
    addRow(list, 'Best move', summary.best_move_san);
    addRow(list, 'Eval before', summary.eval_before?.text ?? '—');
    addRow(list, 'After your move', summary.eval_after?.text ?? '—');
    if (summary.win_percent_drop != null) {
      addRow(list, 'Win% lost', summary.win_percent_drop.toFixed(1));
    }
    addRow(list, 'Attempts', String(summary.attempts));
    if (summary.used_hint) addRow(list, 'Hint', 'used');
    if (summary.used_show_answer) addRow(list, 'Answer', 'revealed');
    body.append(list);
    body.append(paragraph('Review complete — this step is done.', 'choice-note'));
    body.append(
      paragraph(
        '← → step through the whole game. The engine\'s move sits between the position and the move you played.',
        'choice-note',
      ),
    );
    body.append(pgnPasteWidget({ summary: 'Review another game (paste PGN)' }).element);
    promptCard.setBody(body);

    if (!board || !target) return;
    const answer = highlight ?? summary.best_move_uci;
    showNav(review.moves ?? [], { index: target.ply, marked: target.ply });
    // The board is on the answer position right now (just solved, revealed or
    // rebuilt), so that is what the aside shows.
    nav.showAside({
      after: target.ply,
      fen: board.getFen(),
      lastMove: answer,
      shapes: [arrow(answer, 'green')].filter(Boolean),
    });
    renderLichessLink();
    void loadExplanation(target);
  }

  // -- why ---------------------------------------------------------------
  async function loadExplanation(target) {
    const token = ++explainToken;
    whyCard.root.hidden = false;
    whyCard.setBody(paragraph('Working out why…', 'choice-note'));
    let explanation;
    try {
      explanation = await api.reviewExplain(step.step);
    } catch (error) {
      if (token === explainToken && !destroyed) {
        whyCard.setBody(paragraph(`Could not explain this one: ${error.message}`, 'paste-error'));
      }
      return;
    }
    if (token !== explainToken || destroyed) return;
    whyCard.setBody(
      renderExplanation(explanation, {
        // A position from either line sits beside the game, like the answer:
        // ← and → from it step back into the game itself.
        onShow: (move) =>
          nav.showAside({ after: target.ply, fen: move.fen_after, lastMove: move.uci, move }),
      }),
    );
  }

  function hideWhy() {
    explainToken += 1;
    whyCard.root.hidden = true;
    lichessCard.root.hidden = true;
  }

  /**
   * Trying moves of your own is Lichess's job, not this app's: once the review
   * is over, link to the game on its analysis board, opened where it went
   * wrong. The URL only carries the moves, and nothing is sent until clicked.
   */
  function renderLichessLink() {
    const url = review?.lichess_url;
    lichessCard.root.hidden = !url;
    if (!url) return;
    const body = document.createElement('div');
    body.append(
      paragraph(
        review.target
          ? 'Open this game on the Lichess analysis board, at the position where it went wrong, and try the moves yourself.'
          : 'Open this game on the Lichess analysis board and try the moves yourself.',
        'choice-note',
      ),
    );
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noreferrer noopener';
    link.className = 'lichess-link';
    link.textContent = 'Review at Lichess ↗';
    body.append(link);
    lichessCard.setBody(body);
  }

  // -- move navigation ---------------------------------------------------
  /** Load the browsable moves and put the cursor on position `index`. */
  function showNav(moves, { index, marked = null }) {
    nav.setMoves(moves, { index });
    moveList.setMoves(moves, { marked });
    moveList.setCurrent(index);
    latestView = nav.view();
    movesCard.root.hidden = false;
    navRow.hidden = false;
    navReady = true;
    panelChanged();
  }

  function hideNav() {
    hideWhy();
    navReady = false;
    movesCard.root.hidden = true;
    navRow.hidden = true;
    panelChanged();
  }

  /**
   * Draw where the cursor now is. Draws are chained, because each one waits on
   * the server for the position's legal moves, and a held arrow key would
   * otherwise let an older position land after a newer one; any view the
   * cursor has already left is skipped.
   */
  function onNavChange(view) {
    latestView = view;
    moveList.setCurrent(view.aside ? 0 : view.index);
    drawing = drawing
      .then(() => (view === latestView ? drawView(view) : null))
      .catch((error) => setStatus(error.message, 'error'));
  }

  async function drawView(view) {
    if (!board || destroyed) return;
    const target = review?.target;
    const fen = view.fen ?? target?.fen_before ?? board.START_FEN;
    const drilling = Boolean(target) && !review.finished;
    // Only the live position takes a move: anywhere else the drill is paused.
    const live = drilling && !view.aside && view.index === nav.length;

    board.setInteractive(false);
    await board.setFen(fen, { lastMove: squares(view.lastMove) });
    if (view !== latestView || destroyed) return;

    board.setShapes(shapesFor(view));
    board.setHighlights(live ? hintShapes() : []);
    if (live) {
      board.setInteractive(true);
      board.setMoveHandler(handleAttempt);
      setStatus('Your move.');
    } else if (drilling) {
      setStatus('Browsing the game — press End to come back to the position.');
    }
    scheduleEval(fen);
  }

  /**
   * Arrows for a finished review: the engine's move on the aside, and at the
   * position where I went wrong both its move (green) and mine (red).
   */
  function shapesFor(view) {
    const target = review?.target;
    const summary = review?.summary;
    if (!review?.finished || !target || !summary) return [];
    if (view.aside) return view.shapes ?? [];
    const best = arrow(summary.best_move_uci, 'green');
    if (view.index !== target.ply) return [];
    const mine = summary.my_move_uci !== summary.best_move_uci
      ? arrow(summary.my_move_uci, 'red')
      : null;
    return [best, mine].filter(Boolean);
  }

  function scheduleEval(fen) {
    if (evalTimer !== null) clearTimeout(evalTimer);
    evalTimer = setTimeout(() => {
      evalTimer = null;
      void refreshEval(fen);
    }, EVAL_DEBOUNCE_MS);
  }

  function applyCompletion(response) {
    if (response.session) set({ session: response.session });
    if (response.streak) set({ streak: response.streak });
    if (response.session && onCompleted) onCompleted(response.session, { rerender: false });
  }

  // -- helpers -----------------------------------------------------------
  /**
   * The side panel just changed size — the game card, the attempts list and
   * the summary all arrive while the board is up, and the centred layout
   * slides the board sideways when they do. Chessground caches the board's
   * rectangle, so it has to be told, or later clicks read the wrong square.
   */
  function panelChanged() {
    board?.refresh();
  }

  function ensureBoard({ orientation = 'white' } = {}) {
    if (board === null) {
      board = createBoard({ orientation, interactive: false });
      boardAndBar.replaceChildren(board.element, evalBar.element);
      board.refresh();
    } else {
      board.setOrientation(orientation);
    }
    return board;
  }

  function ensureBoardAtStart() {
    const fresh = ensureBoard({ orientation: review?.orientation ?? 'white' });
    fresh.setInteractive(false);
    fresh.setFen(fresh.START_FEN);
  }

  async function refreshEval(fen) {
    // A later position may be asked for before this one comes back (stepping
    // through the game); only the most recent answer may reach the bar.
    const token = ++evalToken;
    evalBar.pending();
    try {
      const response = await api.evaluate(fen);
      if (!destroyed && token === evalToken) evalBar.update(response.evaluation);
    } catch {
      if (token === evalToken) evalBar.clear();
    }
  }

  function pgnPasteWidget(options = {}) {
    return createPgnPaste({
      ...options,
      onSubmit: async (pgn) => {
        const pasted = await api.pastePgn(pgn);
        review = await api.startReview(step.step, {
          gameId: pasted.game.id,
          restart: true,
        });
        attemptLog.length = 0;
        renderAttempts();
        hideNav();
        onReviewState();
      },
    });
  }

  function schedulePoll() {
    stopPolling();
    pollTimer = setTimeout(async () => {
      if (destroyed) return;
      try {
        review = await api.reviewState(step.step);
        onReviewState();
      } catch (error) {
        renderError(error.message);
      }
    }, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  return {
    destroy() {
      destroyed = true;
      stopPolling();
      unbindKeys();
      if (evalTimer !== null) clearTimeout(evalTimer);
      replay?.cancel();
      pause?.cancel();
      board?.destroy();
    },
  };
}

// -- small DOM helpers ----------------------------------------------------
function card(title, onChange) {
  const root = document.createElement('div');
  root.className = 'card';
  const heading = document.createElement('h3');
  heading.textContent = title;
  const body = document.createElement('div');
  root.append(heading, body);
  return {
    root,
    setBody(node) {
      body.replaceChildren(node);
      if (onChange) onChange();
    },
  };
}

function squares(uci) {
  return uci ? [uci.slice(0, 2), uci.slice(2, 4)] : undefined;
}

function arrow(uci, brush) {
  return uci ? { orig: uci.slice(0, 2), dest: uci.slice(2, 4), brush } : null;
}

function navButton(text, title, handler) {
  const element = button(text, handler);
  element.title = title;
  element.setAttribute('aria-label', title);
  // Clicking must not leave focus on the button, or Space/Enter would repeat
  // the step instead of meaning whatever they mean on the page.
  element.addEventListener('mousedown', (event) => event.preventDefault());
  return element;
}

function paragraph(text, className) {
  const element = document.createElement('p');
  if (className) element.className = className;
  element.style.margin = '0 0 10px';
  element.textContent = text;
  return element;
}

function addRow(list, key, value) {
  const dt = document.createElement('dt');
  dt.textContent = key;
  const dd = document.createElement('dd');
  dd.textContent = value;
  list.append(dt, dd);
}

function button(text, handler, className = '') {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = text;
  if (className) element.className = className;
  element.addEventListener('click', async () => {
    try {
      await handler();
    } catch (error) {
      setStatus(error.message, 'error');
    }
  });
  return element;
}
