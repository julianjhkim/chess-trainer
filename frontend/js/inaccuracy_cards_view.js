/**
 * Revision cards (step 1; internally "inaccuracy cards"): slips I picked from
 * my own games, drilled again. Cards are made in step 2 (`make_card_view.js`).
 *
 * Each card is the position before the slip, from my side of the
 * board, with my move drawn as a red arrow. Find the engine's move: retries
 * are unlimited and the eval bar updates on each; *Hint* circles the piece to
 * move (which caps the grade at "right with a hint"); *Show answer* fails the
 * card, so it comes back later in the session. ← / → step through the moves
 * before the slip while solving, and the whole game once it is answered (the
 * answer sits beside the game, between the slip position and my move).
 * *Analyse at Lichess* (once answered) opens the game on Lichess's analysis
 * board at the card's position -- the app has no board of its own for trying
 * moves. *Delete card* (after an inline confirm) takes a card out of the deck.
 *
 * With nothing due -- including before any card has been made -- it says so;
 * the step bar moves on.
 */

import * as api from './api.js';
import { sleep } from './animate.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { lichessButton } from './lichess_button.js';
import { createMoveList } from './move_list.js';
import { bindArrowKeys, createMoveNav } from './move_nav.js';
import { set, setStatus, withStatus } from './state.js';

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
  let result = null;
  let counts = null;
  let hint = null;
  let phase = 'loading'; // loading | solving | finished | empty
  let confirmingDelete = false;
  const attemptLog = [];

  // -- layout ------------------------------------------------------------
  const layout = document.createElement('div');
  layout.className = 'board-layout';

  const boardColumn = document.createElement('div');
  boardColumn.className = 'board-column';
  const boardAndBar = document.createElement('div');
  boardAndBar.className = 'board-and-bar';
  const navRow = document.createElement('div');
  navRow.className = 'button-row nav-row';
  navRow.hidden = true;
  const controls = document.createElement('div');
  controls.className = 'button-row';
  const evalBar = createEvalBar();

  const side = document.createElement('div');
  side.className = 'side-panel';
  const deckCard = card_('Deck', panelChanged);
  const promptCard = card_(step.title, panelChanged);
  const resultCard = card_('Result', panelChanged);
  const movesCard = card_('Moves', panelChanged);
  const attemptsCard = card_('Attempts', panelChanged);
  resultCard.root.hidden = true;
  movesCard.root.hidden = true;
  attemptsCard.root.hidden = true;
  boardColumn.append(boardAndBar, navRow, controls, attemptsCard.root);
  side.append(deckCard.root, promptCard.root, resultCard.root, movesCard.root);

  layout.append(boardColumn, side);
  container.append(layout);

  // -- move navigation ---------------------------------------------------
  let navReady = false;
  let latestView = null;
  let drawing = Promise.resolve();
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

  serveNext();

  // -- serving -----------------------------------------------------------
  async function serveNext() {
    phase = 'loading';
    card = null;
    result = null;
    hint = null;
    confirmingDelete = false;
    attemptLog.length = 0;
    renderAttempts();
    hideNav();
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
    presentCard();
  }

  function presentCard() {
    phase = 'solving';
    const fresh = ensureBoard();
    fresh.setOrientation(card.orientation);
    fresh.setInteractive(false);
    fresh.setShapes([]);
    fresh.setHighlights([]);
    fresh.setMoveHandler(handleAttempt);
    renderPrompt();
    buildControls();
    showNav(card.moves ?? [], { index: (card.moves ?? []).length });
  }

  /**
   * Nothing to drill: before any card has been made, or all caught up.
   * Either way the session goes on to the next step from here.
   */
  function renderEmpty() {
    phase = 'empty';
    hideNav();
    board?.setShapes([]);
    board?.setHighlights([]);
    board?.setInteractive(false);
    const body = document.createElement('div');
    if (!counts?.total) {
      body.append(
        paragraph('No revision cards yet.', 'empty-headline'),
        paragraph(
          'Make one in step 2, “Make a revision card”: paste a game and give the number of the move you got wrong.',
          'choice-note',
        ),
      );
    } else {
      body.append(
        paragraph('All caught up — no revision cards due.', 'empty-headline'),
        paragraph(
          counts.next_due_on
            ? `The next one is due ${counts.next_due_on}.`
            : 'Nothing else is scheduled yet.',
          'choice-note',
        ),
      );
    }
    promptCard.setBody(body);
    buildControls();
    setStatus(counts?.total ? 'No revision cards due.' : 'No revision cards yet.');
  }

  // -- answering ---------------------------------------------------------
  async function handleAttempt(move) {
    if (phase !== 'solving' || destroyed) return;
    board.setInteractive(false);
    let response;
    try {
      response = await api.inaccuracyAttempt(
        move.uci.slice(0, 2),
        move.uci.slice(2, 4),
        move.uci.length > 4 ? move.uci[4] : null,
      );
    } catch (error) {
      setStatus(error.message, 'error');
      redraw();
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
    redraw();
  }

  async function showHint() {
    if (phase !== 'solving') return;
    hint = await withStatus('Asking for a hint…', () => api.inaccuracyHint());
    renderPrompt();
    if (isLive(nav.view())) board?.setHighlights(hintShapes());
    setStatus(hint.text);
  }

  async function showAnswer() {
    if (phase !== 'solving') return;
    board.setInteractive(false);
    const response = await withStatus('Revealing…', () => api.inaccuracyShowAnswer());
    evalBar.update(response.evaluation);
    finish(response);
  }

  function finish(response) {
    phase = 'finished';
    result = response.result;
    board.setHighlights([]);
    board.setInteractive(false);
    if (response.counts) {
      counts = response.counts;
      renderDeck();
    }
    if (response.session) set({ session: response.session });
    if (response.streak) set({ streak: response.streak });
    if (response.session && onCompleted) onCompleted(response.session, { rerender: false });
    renderResult(result);
    buildControls();

    // The whole game opens up; the board shows the answer played, which sits
    // beside the game between the slip position and the move I played.
    showNav(result.moves ?? [], { index: result.ply, marked: result.ply, draw: false });
    nav.showAside({
      after: result.ply,
      fen: response.fen_after,
      lastMove: result.answer_uci,
      shapes: [],
    });
  }

  // -- deleting ----------------------------------------------------------
  function askDelete() {
    confirmingDelete = true;
    buildControls();
  }

  function keepCard() {
    confirmingDelete = false;
    buildControls();
  }

  async function deleteCard() {
    if (!card) return;
    board?.setInteractive(false);
    const label = card.move_label;
    counts = await withStatus('Deleting…', () => api.deleteInaccuracyCard(card.id));
    renderDeck();
    await serveNext();
    if (phase !== 'empty') setStatus(`Deleted the card for ${label}. Your move.`);
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
      paragraph(`From ${from}: move ${card.move_number}, ${side} to play.`, ''),
      playedLine(card.move_label, card.classification),
      paragraph('Find the engine’s move — only its top choice counts. Unlimited retries.', 'choice-note'),
    );
    if (hint) body.append(paragraph(`Hint: ${hint.text}`, 'hint-line'));
    promptCard.setBody(body);
  }

  function renderResult(shown) {
    const body = document.createElement('div');
    const headline = document.createElement('p');
    headline.className = 'result-headline';
    headline.textContent = shown.revealed
      ? `Answer: ${shown.answer_san}`
      : attemptLog.length === 1
        ? `Correct — ${shown.answer_san}, first try.`
        : `Correct — ${shown.answer_san}, after ${attemptLog.length} tries.`;
    body.append(headline);

    const list = document.createElement('dl');
    list.className = 'kv';
    const kind = CLASSIFICATION_LABEL[shown.classification];
    const cost = shown.win_percent_drop != null ? `−${shown.win_percent_drop.toFixed(1)}%` : null;
    const detail = [kind, cost].filter(Boolean).join(', ');
    addRow(list, 'In the game', detail ? `${shown.move_label} (${detail})` : shown.move_label);
    const grade = shown.grade;
    addRow(list, 'Graded', `${grade.description} (q=${grade.quality})`);
    if (grade.interval_days != null) {
      addRow(list, 'Next due', `${grade.due_on} (${grade.interval_days} day${grade.interval_days === 1 ? '' : 's'})`);
    }
    if (grade.ef != null) addRow(list, 'Ease', grade.ef.toFixed(2));
    if (grade.requeued) addRow(list, 'Again', 'later this session');
    body.append(list);
    if (shown.moves?.length) {
      body.append(
        paragraph('← → step through the whole game. The engine’s move sits between the position and the move you played.', 'choice-note'),
      );
    }
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
    if (confirmingDelete && (phase === 'solving' || phase === 'finished')) {
      const question = document.createElement('span');
      question.className = 'delete-question';
      question.textContent = 'Delete this card? It leaves the deck (making it again brings it back).';
      controls.append(question, button('Delete', deleteCard, 'danger'), button('Keep', keepCard));
      panelChanged();
      return;
    }
    if (phase === 'solving') {
      controls.append(button('Hint', showHint), button('Show answer', showAnswer));
    }
    if (phase === 'finished') {
      controls.append(button('Next card', serveNext, 'primary'));
      if (result?.lichess_url) controls.append(lichessButton(result.lichess_url));
    }
    if (phase === 'solving' || phase === 'finished') {
      controls.append(button('Flip board', () => board?.flip()));
    }
    if (phase === 'solving' || phase === 'finished') {
      controls.append(button('Delete card', askDelete, 'subtle-danger'));
    }
    panelChanged();
  }

  // -- drawing -----------------------------------------------------------
  /** Load the moves to step through and put the cursor on position `index`. */
  function showNav(moves, { index, marked = null, draw = true }) {
    nav.setMoves(moves, { index });
    moveList.setMoves(moves, { marked });
    moveList.setCurrent(index);
    latestView = nav.view();
    movesCard.root.hidden = false;
    navRow.hidden = false;
    navReady = true;
    panelChanged();
    if (draw) redraw();
  }

  function hideNav() {
    navReady = false;
    nav.setMoves([], { index: 0 });
    movesCard.root.hidden = true;
    navRow.hidden = true;
    panelChanged();
  }

  function redraw() {
    onNavChange(nav.view());
  }

  /**
   * Draw where the cursor now is. Draws are chained, because each one waits on
   * the board, and a held arrow key would otherwise let an older position land
   * after a newer one; any view the cursor has already left is skipped.
   */
  function onNavChange(view) {
    latestView = view;
    moveList.setCurrent(view.aside ? 0 : view.index);
    drawing = drawing
      .then(() => (view === latestView ? drawView(view) : null))
      .catch((error) => setStatus(error.message, 'error'));
  }

  /** The slip position while solving, where a move is asked for. */
  function isLive(view) {
    return !view.aside && view.index === nav.length && phase === 'solving';
  }

  async function drawView(view) {
    if (!board || destroyed) return;
    const live = isLive(view);
    const fen = live ? card?.fen : (view.fen ?? card?.fen);
    if (!fen) return;
    const lastMove = live ? card?.last_move_uci : view.lastMove;

    board.setInteractive(false);
    // Marks belong to one position: clear them before the board moves.
    board.setShapes([]);
    board.setHighlights([]);
    await board.setFen(fen, { lastMove: squares(lastMove) });
    if (view !== latestView || destroyed) return;

    board.setShapes(shapesFor(view));
    board.setHighlights(live ? hintShapes() : []);
    if (phase === 'solving') {
      if (live) {
        board.setInteractive(true);
        setStatus('Your move.');
      } else {
        setStatus('Browsing the game — press End to come back to the position.');
      }
    }
    void refreshEval(fen);
  }

  /** Once answered: the engine's move (green) and mine (red) at the slip. */
  function shapesFor(view) {
    if (phase !== 'finished' || !result) return [];
    if (view.aside) return view.shapes ?? [];
    if (view.index !== result.ply) return [];
    return [
      arrow(result.answer_uci, 'green'),
      result.my_move_uci !== result.answer_uci ? arrow(result.my_move_uci, 'red') : null,
    ].filter(Boolean);
  }

  /**
   * While solving: the move played in the game (red, what not to play)
   * and the hint's circle, as highlights a click on the board does not wipe.
   */
  function hintShapes() {
    if (phase !== 'solving' || !card) return [];
    const marks = [arrow(card.my_move_uci, 'red')];
    if (hint) marks.push({ orig: hint.square, brush: 'yellow' });
    return marks.filter(Boolean);
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

  let evalToken = 0;
  async function refreshEval(fen) {
    const token = ++evalToken;
    evalBar.pending();
    try {
      const response = await api.evaluate(fen);
      if (!destroyed && token === evalToken) evalBar.update(response.evaluation);
    } catch {
      if (token === evalToken) evalBar.clear();
    }
  }

  return {
    destroy() {
      destroyed = true;
      unbindKeys();
      board?.destroy();
    },
  };
}

// -- small DOM helpers ----------------------------------------------------
/** "You played 2.Nf3 here — a mistake. The red arrow shows it." */
function playedLine(moveLabel, classification) {
  const element = paragraph('', 'played-line');
  element.append('You played ');
  const move = document.createElement('strong');
  move.textContent = moveLabel;
  const kind = CLASSIFICATION_LABEL[classification];
  element.append(move, kind ? ` here — ${kind}. The red arrow shows it.` : ' here. The red arrow shows it.');
  return element;
}

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

function navButton(text, title, handler) {
  const element = button(text, handler);
  element.title = title;
  element.setAttribute('aria-label', title);
  // Clicking must not leave focus on the button, or Space/Enter would repeat
  // the step instead of meaning whatever they mean on the page.
  element.addEventListener('mousedown', (event) => event.preventDefault());
  return element;
}
