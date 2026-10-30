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
 */

import * as api from './api.js';
import { createPause, createReplay, replayDelayFor } from './animate.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { createPgnPaste } from './pgn_paste.js';
import { get, set, setStatus, withStatus } from './state.js';

const POLL_INTERVAL_MS = 700;
const WRONG_MOVE_LINGER_MS = 1100;

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

  boardColumn.append(boardAndBar, controls);

  const side = document.createElement('div');
  side.className = 'side-panel';

  layout.append(boardColumn, side);
  container.append(layout);

  // -- side panel cards --------------------------------------------------
  const gameCard = card('Game', panelChanged);
  const promptCard = card(step.title, panelChanged);
  const attemptsCard = card('Attempts', panelChanged);
  side.append(gameCard.root, promptCard.root, attemptsCard.root);
  attemptsCard.root.hidden = true;

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

    if (review.status === 'failed') {
      renderError(review.error || 'The review failed.');
      return;
    }
    if (review.status === 'analysing') {
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
    gameCard.setBody(list);

    if (game.url) {
      const link = document.createElement('a');
      link.href = game.url;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      link.textContent = 'Open on chess.com ↗';
      link.className = 'choice-note';
      gameCard.root.append(link);
    }
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
    body.append(
      paragraph('No inaccuracy in this game — nothing of yours lost 10% or more. Well played.', ''),
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
    body.append(row, pgnPasteWidget({ summary: 'Review a different game (paste PGN)' }).element);
    promptCard.setBody(body);
    ensureBoardAtStart();
  }

  async function renderTarget() {
    const target = review.target;
    if (!target) return;

    const body = document.createElement('div');
    const whose = target.mover_is_white ? 'White' : 'Black';
    body.append(
      paragraph(`Move ${target.move_number}. This is where your game first went wrong, playing ${whose}.`, ''),
      paragraph(
        'Find the move the engine wants — only its top choice counts. Unlimited retries.',
        'choice-note',
      ),
      // The paste fallback stays available mid-review, so a different game can
      // always be loaded without finishing this one first.
      pgnPasteWidget({ summary: 'Review a different game (paste PGN)' }).element,
    );
    promptCard.setBody(body);

    buildControls();
    await replayToTarget(target);
  }

  async function replayToTarget(target) {
    const orientation = review.orientation;
    const fresh = ensureBoard({ orientation });
    await fresh.setFen(fresh.START_FEN);
    fresh.setInteractive(false);
    fresh.setShapes([]);

    setStatus(target.replay_ucis.length ? 'Replaying the game…' : 'Your move.');
    replay = createReplay({
      board: fresh,
      ucis: target.replay_ucis,
      delayMs: replayDelayFor(target.replay_ucis.length),
    });
    const completed = await replay.promise;
    if (destroyed || !completed) return;

    await refreshEval(target.fen_before);
    fresh.setInteractive(true);
    fresh.setMoveHandler(handleAttempt);
    setStatus('Your move.');
  }

  function buildControls() {
    controls.replaceChildren();
    controls.append(
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
  }

  async function showAnswer() {
    const target = review?.target;
    if (!target) return;
    board?.setInteractive(false);
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
    headline.textContent = revealed
      ? 'Answer revealed.'
      : summary.solved_first_try
        ? 'Correct, first try.'
        : `Correct, after ${summary.attempts} attempts.`;
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
    if (summary.used_show_answer) addRow(list, 'Answer', 'revealed');
    body.append(list);
    body.append(paragraph('Review complete — this step is done.', 'choice-note'));
    body.append(pgnPasteWidget({ summary: 'Review another game (paste PGN)' }).element);
    promptCard.setBody(body);

    if (highlight && board) {
      board.setShapes([
        { orig: highlight.slice(0, 2), dest: highlight.slice(2, 4), brush: 'green' },
      ]);
    }
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
    evalBar.pending();
    try {
      const response = await api.evaluate(fen);
      if (!destroyed) evalBar.update(response.evaluation);
    } catch {
      evalBar.clear();
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
