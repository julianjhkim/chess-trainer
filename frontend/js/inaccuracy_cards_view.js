/**
 * Inaccuracy cards (step 1): the first slip of each reviewed game, again.
 *
 * Each card is the position before a slip, from my side of the board, with the
 * move that led there highlighted. Find the engine's move: retries are
 * unlimited and the eval bar updates on each; *Hint* circles the piece to move
 * (which caps the grade at "right with a hint"); *Show answer* fails the card,
 * so it comes back later in the session. The result shows the answer (green)
 * and the move played in the game (red), with the grade and next due date.
 *
 * With nothing due -- including before any game has been reviewed -- it says
 * so and offers to go on to the next step.
 */

import * as api from './api.js';
import { sleep } from './animate.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { get, set, setStatus, withStatus } from './state.js';

const WRONG_MOVE_LINGER_MS = 1000;

const CLASSIFICATION_LABEL = {
  inaccuracy: 'an inaccuracy',
  mistake: 'a mistake',
  blunder: 'a blunder',
};

const SOURCE_LABEL = { due: 'Review', relearn: 'Again' };

export function renderInaccuracyCardsView(container, { step, onCompleted }) {
  container.replaceChildren();

  let destroyed = false;
  let board = null;
  let card = null;
  let counts = null;
  let hint = null;
  let phase = 'loading'; // loading | solving | finished | empty
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
  const evalBar = createEvalBar();

  const side = document.createElement('div');
  side.className = 'side-panel';
  const deckCard = card_('Deck', panelChanged);
  const promptCard = card_(step.title, panelChanged);
  const resultCard = card_('Result', panelChanged);
  const attemptsCard = card_('Attempts', panelChanged);
  resultCard.root.hidden = true;
  attemptsCard.root.hidden = true;
  boardColumn.append(boardAndBar, controls, attemptsCard.root);
  side.append(deckCard.root, promptCard.root, resultCard.root);

  layout.append(boardColumn, side);
  container.append(layout);

  serveNext();

  // -- serving -----------------------------------------------------------
  async function serveNext() {
    phase = 'loading';
    card = null;
    hint = null;
    attemptLog.length = 0;
    renderAttempts();
    resultCard.root.hidden = true;
    controls.replaceChildren();
    promptCard.setBody(paragraph('Finding your next card…', 'choice-note'));

    let state;
    try {
      state = await api.nextInaccuracyCard();
    } catch (error) {
      promptCard.setBody(paragraph(error.message, 'paste-error'));
      setStatus(error.message, 'error');
      return;
    }
    if (destroyed) return;
    counts = state.counts;
    renderDeck();

    if (!state.card) {
      renderEmpty();
      return;
    }
    card = state.card;
    await presentCard();
  }

  async function presentCard() {
    phase = 'solving';
    const fresh = ensureBoard();
    fresh.setOrientation(card.orientation);
    fresh.setInteractive(false);
    fresh.setShapes([]);
    fresh.setHighlights([]);
    await fresh.setFen(card.fen, { lastMove: squares(card.last_move_uci) });
    if (destroyed) return;
    renderPrompt();
    buildControls();
    void refreshEval(card.fen);
    fresh.setMoveHandler(handleAttempt);
    fresh.setInteractive(true);
    setStatus('Your move.');
  }

  /**
   * Nothing to drill: before any review has made a card, or all caught up.
   * Either way the session goes on to the next step from here.
   */
  function renderEmpty() {
    phase = 'empty';
    const body = document.createElement('div');
    if (!counts?.total) {
      body.append(
        paragraph('No inaccuracy cards yet.', 'empty-headline'),
        paragraph(
          'Play a game and review it: the first slip in each reviewed game becomes a card here, first due the next day.',
          'choice-note',
        ),
      );
    } else {
      body.append(
        paragraph('All caught up — no inaccuracy cards due.', 'empty-headline'),
        paragraph(
          counts.next_due_on
            ? `The next one is due ${counts.next_due_on}.`
            : 'Nothing else is scheduled yet.',
          'choice-note',
        ),
      );
    }
    const row = document.createElement('div');
    row.className = 'button-row';
    row.append(button('Continue to Play a game', moveOn, 'primary'));
    body.append(row);
    promptCard.setBody(body);
    setStatus(counts?.total ? 'No inaccuracy cards due.' : 'No inaccuracy cards yet.');
  }

  /**
   * Go on to the next step. Having answered a card, the step is already done
   * and completing it just advances; with nothing answered it is skipped
   * rather than completed, so an empty deck never counts towards the streak.
   */
  async function moveOn() {
    const session = get().session;
    const done = session?.steps.find((s) => s.step === step.step)?.completed;
    const next = done
      ? (await withStatus('Moving on…', () => api.completeStep(step.step))).session
      : await withStatus('Moving on…', () => api.jumpToStep('play'));
    set({ session: next });
    if (onCompleted) onCompleted(next);
  }

  // -- answering ---------------------------------------------------------
  async function handleAttempt(result) {
    if (phase !== 'solving' || destroyed) return;
    board.setInteractive(false);
    let response;
    try {
      response = await api.inaccuracyAttempt(
        result.uci.slice(0, 2),
        result.uci.slice(2, 4),
        result.uci.length > 4 ? result.uci[4] : null,
      );
    } catch (error) {
      setStatus(error.message, 'error');
      await board.setFen(card.fen, { lastMove: squares(card.last_move_uci) });
      board.setInteractive(true);
      return;
    }

    evalBar.update(response.evaluation);
    attemptLog.push({ san: response.san, text: response.evaluation.text, correct: response.correct });
    renderAttempts();

    if (response.correct) {
      setStatus('Correct.');
      finish(response);
      return;
    }

    setStatus(`${response.san} is not it — try again.`);
    await sleep(WRONG_MOVE_LINGER_MS);
    if (destroyed || phase !== 'solving') return;
    await board.setFen(card.fen, { lastMove: squares(card.last_move_uci) });
    board.setHighlights(hintShapes());
    board.setInteractive(true);
  }

  async function showHint() {
    if (phase !== 'solving') return;
    hint = await withStatus('Asking for a hint…', () => api.inaccuracyHint());
    renderPrompt();
    board?.setHighlights(hintShapes());
    setStatus(hint.text);
  }

  async function showAnswer() {
    if (phase !== 'solving') return;
    board.setInteractive(false);
    const response = await withStatus('Revealing…', () => api.inaccuracyShowAnswer());
    await board.setFen(card.fen, { lastMove: squares(card.last_move_uci) });
    await board.pushMove(response.uci);
    evalBar.update(response.evaluation);
    finish(response);
  }

  function finish(response) {
    phase = 'finished';
    const result = response.result;
    board.setHighlights([]);
    board.setInteractive(false);
    // The answer, and the move played in the game, both from the position.
    board.setShapes(
      [arrow(result.answer_uci, 'green'), result.my_move_uci !== result.answer_uci ? arrow(result.my_move_uci, 'red') : null]
        .filter(Boolean),
    );
    if (response.counts) {
      counts = response.counts;
      renderDeck();
    }
    if (response.session) set({ session: response.session });
    if (response.streak) set({ streak: response.streak });
    if (response.session && onCompleted) onCompleted(response.session, { rerender: false });
    renderResult(result);
    buildControls();
  }

  // -- panels ------------------------------------------------------------
  function renderDeck() {
    const list = document.createElement('dl');
    list.className = 'kv';
    addRow(list, 'Due', String(counts?.due ?? 0));
    if (counts?.relearning) addRow(list, 'Again today', String(counts.relearning));
    addRow(list, 'In the deck', String(counts?.total ?? 0));
    deckCard.setBody(list);
  }

  function renderPrompt() {
    const body = document.createElement('div');
    const tag = document.createElement('p');
    tag.className = 'choice-note';
    tag.style.margin = '0 0 6px';
    tag.textContent = SOURCE_LABEL[card.source] ?? 'Review';
    const side = card.orientation === 'white' ? 'White' : 'Black';
    const from = [
      card.opponent ? `your game vs ${card.opponent}` : 'one of your games',
      card.played_on ? new Date(card.played_on * 1000).toISOString().slice(0, 10) : null,
    ].filter(Boolean).join(', ');
    body.append(
      tag,
      paragraph(
        `From ${from}: move ${card.move_number}, ${side} to play. You played ${CLASSIFICATION_LABEL[card.classification] ?? card.classification} here.`,
        '',
      ),
      paragraph('Find the engine’s move — only its top choice counts. Unlimited retries.', 'choice-note'),
    );
    if (hint) body.append(paragraph(`Hint: ${hint.text}`, 'hint-line'));
    promptCard.setBody(body);
  }

  function renderResult(result) {
    const body = document.createElement('div');
    const headline = document.createElement('p');
    headline.className = 'result-headline';
    headline.textContent = result.revealed
      ? `Answer: ${result.answer_san}`
      : attemptLog.length === 1
        ? `Correct — ${result.answer_san}, first try.`
        : `Correct — ${result.answer_san}, after ${attemptLog.length} tries.`;
    body.append(headline);

    const list = document.createElement('dl');
    list.className = 'kv';
    const cost = result.win_percent_drop != null ? `, −${result.win_percent_drop.toFixed(1)}%` : '';
    addRow(list, 'In the game', `${result.move_label} (${CLASSIFICATION_LABEL[result.classification] ?? result.classification}${cost})`);
    const grade = result.grade;
    addRow(list, 'Graded', `${grade.description} (q=${grade.quality})`);
    if (grade.interval_days != null) {
      addRow(list, 'Next due', `${grade.due_on} (${grade.interval_days} day${grade.interval_days === 1 ? '' : 's'})`);
    }
    if (grade.ef != null) addRow(list, 'Ease', grade.ef.toFixed(2));
    if (grade.requeued) addRow(list, 'Again', 'later this session');
    body.append(list);
    resultCard.setBody(body);
    resultCard.root.hidden = false;
    panelChanged();
  }

  function renderAttempts() {
    attemptsCard.root.hidden = attemptLog.length === 0;
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

  function buildControls() {
    controls.replaceChildren();
    if (phase === 'solving') {
      controls.append(button('Hint', showHint), button('Show answer', showAnswer));
    }
    if (phase === 'finished') {
      controls.append(button('Next card', serveNext, 'primary'));
    }
    controls.append(button('Flip board', () => board?.flip()));
  }

  function hintShapes() {
    return hint && phase === 'solving' ? [{ orig: hint.square, brush: 'yellow' }] : [];
  }

  // -- helpers -----------------------------------------------------------
  /** Cards beside and under the board change size; chessground must re-measure. */
  function panelChanged() {
    board?.refresh();
  }

  function ensureBoard() {
    if (board === null) {
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
      board?.destroy();
    },
  };
}

// -- small DOM helpers ----------------------------------------------------
function squares(uci) {
  return uci ? [uci.slice(0, 2), uci.slice(2, 4)] : undefined;
}

function arrow(uci, brush) {
  return uci ? { orig: uci.slice(0, 2), dest: uci.slice(2, 4), brush } : null;
}

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
