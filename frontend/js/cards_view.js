/**
 * Opening cards (step 4).
 *
 * One card runs like this:
 *
 *   1. the earlier moves of the line auto-play quickly
 *   2. the branch move is shown as an arrow; you play it
 *   3. the opening name appears
 *   4. you find the answer move, with no arrow; retries are unlimited and the
 *      eval bar updates after each one
 *   5. the stats table, the grade and any "max depth reached" lines appear
 *
 * White stays at the bottom by default, with a Flip board button.
 */

import * as api from './api.js';
import { createReplay, replayDelayFor, sleep } from './animate.js';
import * as arrows from './arrows.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { set, setStatus, withStatus } from './state.js';
import { renderStatsTable } from './stats_table.js';

const WRONG_MOVE_LINGER_MS = 1000;

// Said on the question screen, before the answer is known: whether the move
// the masters played most is the one Stockfish would play.
const ENGINE_AGREES = "The most played move is also the engine's best move.";
const ENGINE_DISAGREES =
  "Heads-up: the most played move is NOT the engine's best move — find the most played one.";

const SOURCE_LABEL = {
  new: 'New card',
  due: 'Review',
  relearn: 'Again',
};

export function renderCardsView(container, { step, onCompleted }) {
  container.replaceChildren();

  let destroyed = false;
  let replay = null;
  let board = null;
  let card = null;
  let counts = null;
  let phase = 'loading'; // loading | given | solving | finished | exhausted
  const attemptLog = [];

  // -- layout ------------------------------------------------------------
  const layout = document.createElement('div');
  layout.className = 'board-layout';

  const boardColumn = document.createElement('div');
  boardColumn.className = 'board-column';
  const boardAndBar = document.createElement('div');
  boardAndBar.className = 'board-and-bar';
  const controls = document.createElement('div');
  controls.className = 'button-row';
  boardColumn.append(boardAndBar, controls);

  const evalBar = createEvalBar();

  const side = document.createElement('div');
  side.className = 'side-panel side-panel-wide';

  const queueCard = card_('Queue', panelChanged);
  const promptCard = card_(step.title, panelChanged);
  const resultCard = card_('Result', panelChanged);
  resultCard.root.hidden = true;
  side.append(queueCard.root, promptCard.root, resultCard.root);

  layout.append(boardColumn, side);
  container.append(layout);

  serveNext();

  // -- serving -----------------------------------------------------------
  async function serveNext() {
    phase = 'loading';
    resultCard.root.hidden = true;
    attemptLog.length = 0;
    promptCard.setBody(paragraph('Finding your next card…', 'choice-note'));
    controls.replaceChildren();

    let state;
    try {
      state = await api.nextCard();
    } catch (error) {
      promptCard.setBody(paragraph(error.message, 'paste-error'));
      setStatus(error.message, 'error');
      return;
    }
    if (destroyed) return;

    counts = state.counts;
    renderQueue();

    if (!state.card) {
      phase = 'exhausted';
      promptCard.setBody(
        paragraph(
          'Nothing due and no new cards left to introduce. Come back tomorrow, or play a game.',
          '',
        ),
      );
      return;
    }

    card = state.card;
    await presentCard();
  }

  async function presentCard() {
    phase = 'given';
    const fresh = ensureBoard();
    fresh.setInteractive(false);
    fresh.setShapes([]);
    await fresh.setFen(fresh.START_FEN);

    renderPrompt();
    buildControls();

    // 1. Replay the earlier moves of the line quickly.
    if (card.replay_ucis.length) {
      setStatus('Replaying the line…');
      replay = createReplay({
        board: fresh,
        ucis: card.replay_ucis,
        delayMs: replayDelayFor(card.replay_ucis.length),
      });
      const done = await replay.promise;
      if (destroyed || !done) return;
    }

    // 2. Show the branch move as an arrow and wait for it to be played.
    fresh.setShapes(arrows.givenMove(card.given_move_uci));
    fresh.setInteractive(true);
    fresh.restrictTo(card.given_move_uci);
    fresh.setMoveHandler(handleGivenMove);
    setStatus(`Play the arrow: ${card.given_move_san}`);
    renderPrompt();
  }

  // -- the given move ----------------------------------------------------
  async function handleGivenMove(result) {
    if (destroyed || phase !== 'given') return;
    if (result.uci !== card.given_move_uci) {
      // restrictTo should prevent this, but never trust the board.
      await board.setFen(card.fen_before_given);
      board.restrictTo(card.given_move_uci);
      setStatus('Play the move the arrow shows.');
      return;
    }

    phase = 'solving';
    board.setShapes([]);
    board.clearRestriction();
    board.setMoveHandler(handleAttempt);
    await refreshEval(card.fen);
    renderPrompt();
    buildControls();
    setStatus(`Your move as ${card.side_to_move}.`);
  }

  // -- answering ---------------------------------------------------------
  async function handleAttempt(result) {
    if (destroyed || phase !== 'solving') return;
    board.setInteractive(false);

    let response;
    try {
      response = await api.cardAttempt(
        result.uci.slice(0, 2),
        result.uci.slice(2, 4),
        result.uci.length > 4 ? result.uci[4] : null,
      );
    } catch (error) {
      setStatus(error.message, 'error');
      await board.setFen(card.fen);
      board.setInteractive(true);
      return;
    }

    evalBar.update(response.evaluation);
    attemptLog.push({
      san: response.san,
      text: response.evaluation.text,
      correct: response.correct,
    });

    if (response.correct) {
      phase = 'finished';
      board.setShapes(arrows.answerMove(response.uci));
      setStatus('Correct.');
      applyProgress(response);
      renderResult(response, { revealed: false });
      return;
    }

    setStatus(`${response.san} is not the move — try again.`);
    renderPrompt();
    await sleep(WRONG_MOVE_LINGER_MS);
    if (destroyed || phase !== 'solving') return;
    await board.setFen(card.fen);
    board.setInteractive(true);
  }

  async function showAnswer() {
    if (phase !== 'solving') return;
    board.setInteractive(false);
    const response = await withStatus('Revealing…', () => api.showCardAnswer());
    phase = 'finished';
    await board.setFen(card.fen);
    await board.pushMove(response.answer_uci);
    board.setShapes(arrows.answerMove(response.answer_uci));
    evalBar.update(response.evaluation);
    applyProgress(response);
    renderResult(response, { revealed: true });
  }

  function applyProgress(response) {
    if (response.counts) {
      counts = response.counts;
      renderQueue();
    }
    if (response.session) set({ session: response.session });
    if (response.streak) set({ streak: response.streak });
    if (response.session && onCompleted) onCompleted(response.session, { rerender: false });
  }

  // -- panels ------------------------------------------------------------
  function renderQueue() {
    const list = document.createElement('dl');
    list.className = 'kv';
    addRow(list, 'Due', String(counts?.due ?? 0));
    addRow(list, 'New', String(counts?.new ?? 0));
    if (counts?.relearning) addRow(list, 'Again today', String(counts.relearning));
    queueCard.setBody(list);
  }

  function renderPrompt() {
    const body = document.createElement('div');

    const header = document.createElement('p');
    header.className = 'card-line';
    header.append(label(SOURCE_LABEL[card.source] ?? card.source, `tag-${card.source}`));
    const lineText = document.createElement('span');
    lineText.className = 'mono';
    lineText.textContent = card.line_label;
    header.append(lineText);
    body.append(header);

    if (phase === 'given') {
      body.append(
        paragraph(`Play ${card.given_move_san} — the arrow shows it.`, ''),
        paragraph('The opening name appears once you have played it.', 'choice-note'),
      );
    } else {
      if (card.opening_label) {
        const opening = document.createElement('p');
        opening.className = 'opening-name';
        opening.textContent = card.opening_label;
        body.append(opening);
      }
      body.append(
        paragraph(
          `Find the move for ${card.side_to_move}. No arrow this time.`,
          '',
        ),
      );
      if (card.mode === 'engine') {
        body.append(
          paragraph(
            `Only ${card.position_games} master games here, so Stockfish's move is the answer.`,
            'choice-note',
          ),
        );
      } else {
        body.append(
          paragraph(
            `${card.position_games.toLocaleString()} master games — the most played move is the answer.`,
            'choice-note',
          ),
        );
        // Whether Stockfish would play the same move, decided before the card
        // was shown. Which move either one is stays unsaid: that is the
        // question. `null` means there is nothing to say, not "no".
        if (card.engine_agrees !== null && card.engine_agrees !== undefined) {
          body.append(
            paragraph(
              card.engine_agrees ? ENGINE_AGREES : ENGINE_DISAGREES,
              card.engine_agrees ? 'engine-agrees' : 'engine-disagrees',
            ),
          );
        }
      }
    }

    if (attemptLog.length) body.append(renderAttempts());
    promptCard.setBody(body);
  }

  function renderAttempts() {
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
    return list;
  }

  function renderResult(response, { revealed }) {
    const body = document.createElement('div');

    const headline = document.createElement('p');
    headline.className = 'result-headline';
    headline.textContent = revealed
      ? `Answer: ${response.answer_san}`
      : attemptLog.length === 1
        ? `Correct — ${response.answer_san}, first try.`
        : `Correct — ${response.answer_san}, after ${attemptLog.length} tries.`;
    body.append(headline);

    const grade = response.grade;
    if (grade) {
      const list = document.createElement('dl');
      list.className = 'kv';
      addRow(list, 'Graded', `${grade.description} (q=${grade.quality})`);
      if (grade.interval_days != null) {
        addRow(
          list,
          'Next due',
          `${grade.due_on} (${grade.interval_days} day${grade.interval_days === 1 ? '' : 's'})`,
        );
      }
      if (grade.ef != null) addRow(list, 'Ease', grade.ef.toFixed(2));
      if (grade.requeued) addRow(list, 'Again', 'later this session');
      if (response.branches_created) {
        addRow(
          list,
          'Unlocked',
          `${response.branches_created} new card${response.branches_created === 1 ? '' : 's'}`,
        );
      }
      body.append(list);
    }

    if (card.opening_label) {
      const opening = document.createElement('p');
      opening.className = 'opening-name';
      opening.textContent = card.opening_label;
      body.append(opening);
    }

    body.append(renderStatsTable(response.stats));

    for (const dead of response.dead_ends ?? []) {
      body.append(renderDeadEnd(dead));
    }

    promptCard.setBody(body);
    resultCard.root.hidden = true;

    controls.replaceChildren(
      button('Next card', serveNext, 'primary'),
      button('Flip board', () => board?.flip()),
    );
  }

  function renderDeadEnd(dead) {
    const box = document.createElement('div');
    box.className = 'dead-end';

    const title = document.createElement('p');
    title.className = 'dead-end-title';
    title.textContent = `${dead.message}: ${dead.line_label}`;
    box.append(title);

    const detail = document.createElement('p');
    detail.className = 'choice-note';
    detail.textContent = dead.detail ?? '';
    box.append(detail);

    const stats = document.createElement('p');
    stats.className = 'mono choice-note';
    const rating = dead.average_rating ? `, avg ${dead.average_rating}` : '';
    stats.textContent = `${dead.games} game${dead.games === 1 ? '' : 's'} — W/D/L ${dead.white}/${dead.draws}/${dead.black}${rating}`;
    box.append(stats);
    return box;
  }

  function buildControls() {
    controls.replaceChildren();
    if (phase === 'solving') {
      controls.append(button('Show answer', showAnswer));
    }
    controls.append(button('Flip board', () => board?.flip()));
    if (phase === 'given') {
      controls.append(button('Replay line', presentCard));
    }
  }

  // -- helpers -----------------------------------------------------------
  /**
   * The side panel just changed size: the opening name, the stats table and
   * the grade all land in it mid-card, and the centred layout slides the board
   * sideways when they do. Chessground caches the board's rectangle, so it has
   * to be told, or every later click reads a square too far to the left.
   */
  function panelChanged() {
    board?.refresh();
  }

  function ensureBoard() {
    if (board === null) {
      // White at the bottom by default, whichever side the card asks about.
      board = createBoard({ orientation: 'white', interactive: false });
      boardAndBar.replaceChildren(board.element, evalBar.element);
      board.refresh();
    }
    return board;
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

  return {
    destroy() {
      destroyed = true;
      replay?.cancel();
      board?.destroy();
    },
  };
}

// -- small DOM helpers ----------------------------------------------------
function card_(title, onChange) {
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

function label(text, className) {
  const element = document.createElement('span');
  element.className = `tag ${className}`;
  element.textContent = text;
  return element;
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
