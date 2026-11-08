/**
 * Puzzles (step 1; internally "inaccuracy cards"): the puzzles found in my own
 * games, drilled again. They are made in step 2 (`make_card_view.js`).
 *
 * A puzzle is either the position right after a mistake -- mine or my
 * opponent's -- played by the side that can punish it (the mistake plays in
 * first), or, for older puzzles, the position before my slip. The prompt says
 * whose mistake it was and which side I had; no arrow marks the game's move. Find the
 * engine's move: retries are unlimited and the eval bar updates on each.
 * Where the line is forcing the card is a puzzle -- a right move brings the
 * opponent's reply, played for me, and I go on until the line ends; the moves
 * join the move list as they are played. *Hint* circles the piece to move at
 * the current step (which caps the grade at "right with a hint"); *Show
 * answer* plays out the rest and fails the card, so it comes back later in the
 * session. ← / → step through the moves before the live position while
 * solving, and the whole game once it is answered (the puzzle line sits beside
 * the game, between the slip position and my move).
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
/** Pauses before the opponent's move plays: at the start, and after mine. */
const OPENING_MOVE_PAUSE_MS = 600;
const REPLY_PAUSE_MS = 450;

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
  /** The position a move is asked for: the card's, then each puzzle step's. */
  let live = null;
  /** The game's moves before the slip, then the puzzle moves played so far. */
  let solvingMoves = [];
  /** Puzzle moves played so far (mine and the replies). */
  let stepPlies = 0;
  /** Bumped for every card, so a pause from an older card does nothing. */
  let cardToken = 0;
  /** True while an opponent's move is about to play in (no "browsing" note). */
  let pausing = false;

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
    cardToken += 1;
    pausing = false;
    card = null;
    result = null;
    hint = null;
    confirmingDelete = false;
    attemptLog.length = 0;
    renderAttempts();
    hideNav();
    resultCard.root.hidden = true;
    controls.replaceChildren();
    promptCard.setBody(paragraph('Finding your next puzzle…', 'choice-note'));

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

  async function presentCard() {
    phase = 'solving';
    const token = ++cardToken;
    live = { fen: card.fen, lastMove: card.last_move_uci };
    solvingMoves = [...(card.moves ?? [])];
    stepPlies = 0;
    const fresh = ensureBoard();
    fresh.setOrientation(card.orientation);
    fresh.setInteractive(false);
    fresh.setShapes([]);
    fresh.setHighlights([]);
    fresh.setMoveHandler(handleAttempt);
    renderPrompt();
    buildControls();
    if (!solvingMoves.length) {
      showNav(solvingMoves, { index: 0 });
      return;
    }
    // As in a puzzle on Lichess: the opponent's last move plays in first.
    pausing = true;
    showNav(solvingMoves, { index: solvingMoves.length - 1 });
    await sleep(OPENING_MOVE_PAUSE_MS);
    if (token !== cardToken) return;
    pausing = false;
    if (phase === 'solving' && nav.index === solvingMoves.length - 1) nav.last();
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
        paragraph('No puzzles yet.', 'empty-headline'),
        paragraph(
          'Make some in step 2, “Make puzzles”: paste one of your games and the engine finds the puzzles in it.',
          'choice-note',
        ),
      );
    } else {
      body.append(
        paragraph('All caught up — no puzzles due.', 'empty-headline'),
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
    setStatus(counts?.total ? 'No puzzles due.' : 'No puzzles yet.');
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

    if (response.correct && response.finished) {
      setStatus('Correct.');
      finish(response);
      return;
    }
    if (response.correct) {
      await playReply(response);
      return;
    }

    setStatus(`${response.san} is not it — try again.`);
    await sleep(WRONG_MOVE_LINGER_MS);
    if (destroyed || phase !== 'solving') return;
    redraw();
  }

  /** A right move with more to come: mine joins the list, then the reply plays. */
  async function playReply(response) {
    const token = cardToken;
    const [mine, reply] = response.played;
    hint = null;
    stepPlies += 2;
    solvingMoves = [...solvingMoves, mine, reply];
    live = { fen: reply.fen_after, lastMove: reply.uci };
    renderPrompt();
    setStatus(`Right — ${mine.san}. Now ${reply.san}…`);
    pausing = true;
    showNav(solvingMoves, { index: solvingMoves.length - 1 });
    await sleep(REPLY_PAUSE_MS);
    if (token !== cardToken) return;
    pausing = false;
    if (phase === 'solving' && !destroyed) nav.last();
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

    // The whole game opens up; the board shows the end of the puzzle line,
    // which sits beside the game between the slip position and my move.
    showNav(result.moves ?? [], { index: result.ply, marked: result.ply, draw: false });
    const line = (result.solution ?? []).map((move) => ({
      fen: move.fen_after,
      lastMove: move.uci,
      move,
      shapes: [],
    }));
    if (!line.length) line.push({ fen: response.fen_after, lastMove: result.answer_uci, shapes: [] });
    nav.showAside({ after: result.ply, line });
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
    if (phase !== 'empty') setStatus(`Deleted the puzzle for ${label}. Your move.`);
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
    const side = colourName(card.orientation);
    const from = [
      card.opponent ? `Your game vs ${card.opponent}` : 'One of your games',
      card.played_on ? new Date(card.played_on * 1000).toISOString().slice(0, 10) : null,
    ].filter(Boolean).join(', ');
    body.append(
      tag,
      paragraph(`${from} — you had ${colourName(card.my_colour ?? card.orientation)}.`, ''),
      mistakeLine(card, side),
      paragraph(
        'Find the best move — only Stockfish’s top choice counts. Your opponent replies, and you go on until the puzzle ends. Unlimited retries.',
        'choice-note',
      ),
    );
    if (stepPlies > 0) {
      body.append(paragraph(`So far: ${lineText(solvingMoves.slice(-stepPlies))} — your move.`, 'played-line'));
    }
    if (hint) body.append(paragraph(`Hint: ${hint.text}`, 'hint-line'));
    promptCard.setBody(body);
  }

  function renderResult(shown) {
    const body = document.createElement('div');
    const headline = document.createElement('p');
    headline.className = 'result-headline';
    const solution = shown.solution?.length ? lineText(shown.solution) : shown.answer_san;
    const wrong = attemptLog.filter((entry) => !entry.correct).length;
    const puzzle = (shown.solution?.length ?? 0) > 1;
    headline.textContent = shown.revealed
      ? `${puzzle ? 'Solution' : 'Answer'}: ${solution}`
      : wrong === 0
        ? `Correct — ${solution}, no wrong moves.`
        : `Correct — ${solution}, after ${wrong} wrong move${wrong === 1 ? '' : 's'}.`;
    body.append(headline);

    const list = document.createElement('dl');
    list.className = 'kv';
    const kind = CLASSIFICATION_LABEL[shown.classification];
    const cost = shown.win_percent_drop != null ? `−${shown.win_percent_drop.toFixed(1)}%` : null;
    const detail = [kind, cost].filter(Boolean).join(', ');
    const slip = detail ? `${shown.move_label} (${detail})` : shown.move_label;
    if (shown.kind === 'punish') {
      addRow(list, shown.slip_mine ? 'Your mistake' : 'Their mistake', slip);
      addRow(list, 'The game went on', shown.played_label ?? 'it ended there');
    } else {
      addRow(list, 'In the game', slip);
    }
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
        paragraph('← → step through the whole game. The engine’s line sits beside it, between the position and the move you played.', 'choice-note'),
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
      question.textContent = 'Delete this puzzle? It leaves the deck (scanning the game again brings it back).';
      controls.append(question, button('Delete', deleteCard, 'danger'), button('Keep', keepCard));
      panelChanged();
      return;
    }
    if (phase === 'solving') {
      controls.append(button('Hint', showHint), button('Show answer', showAnswer));
    }
    if (phase === 'finished') {
      controls.append(button('Next puzzle', serveNext, 'primary'));
      if (result?.lichess_url) controls.append(lichessButton(result.lichess_url));
    }
    if (phase === 'solving' || phase === 'finished') {
      controls.append(button('Flip board', () => board?.flip()));
    }
    if (phase === 'solving' || phase === 'finished') {
      controls.append(button('Delete puzzle', askDelete, 'subtle-danger'));
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

  /** The position a move is asked for, while solving. */
  function isLive(view) {
    return !view.aside && view.index === nav.length && phase === 'solving';
  }

  async function drawView(view) {
    if (!board || destroyed) return;
    const atLive = isLive(view);
    const fen = atLive ? live?.fen : (view.fen ?? card?.fen);
    if (!fen) return;
    const lastMove = atLive ? live?.lastMove : view.lastMove;

    board.setInteractive(false);
    // Marks belong to one position: clear them before the board moves.
    board.setShapes([]);
    board.setHighlights([]);
    await board.setFen(fen, { lastMove: squares(lastMove) });
    if (view !== latestView || destroyed) return;

    board.setShapes(shapesFor(view));
    board.setHighlights(atLive ? hintShapes() : []);
    if (phase === 'solving') {
      if (atLive) {
        board.setInteractive(true);
        setStatus(stepPlies ? `${solvingMoves.at(-1).san} — your move.` : 'Your move.');
      } else if (!pausing) {
        setStatus('Browsing the game — press End to come back to the position.');
      }
    }
    void refreshEval(fen);
  }

  /** Once answered: the engine's move (green) at the puzzle's position. */
  function shapesFor(view) {
    if (phase !== 'finished' || !result) return [];
    if (view.aside) return view.shapes ?? [];
    if (view.index !== result.ply) return [];
    return [arrow(result.answer_uci, 'green')].filter(Boolean);
  }

  /** While solving: the hint's circle, as a highlight a click does not wipe. */
  function hintShapes() {
    if (phase !== 'solving' || !card || !hint) return [];
    return [{ orig: hint.square, brush: 'yellow' }];
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
/**
 * Whose mistake the puzzle is about, and what to do, e.g. "Your mistake:
 * 8.Bb3 (a mistake). You play Black now: punish it, as your opponent should
 * have." -- so the side you play never hides which side you had.
 */
function mistakeLine(card, side) {
  const element = paragraph('', 'played-line');
  const label = document.createElement('strong');
  const move = document.createElement('strong');
  move.textContent = card.move_label;
  const kind = CLASSIFICATION_LABEL[card.classification] ?? 'a mistake';
  if (card.kind !== 'punish') {
    label.textContent = 'Your mistake: ';
    element.append(label, move, ` (${kind}). Find what you should have played instead — ${side} to play.`);
  } else if (card.slip_mine) {
    label.textContent = 'Your mistake: ';
    element.append(label, move, ` (${kind}). You play ${side} now: punish it, as your opponent should have.`);
  } else {
    label.textContent = 'Their mistake: ';
    element.append(label, move, ` (${kind}). You play ${side}: punish it.`);
  }
  return element;
}

function colourName(colour) {
  return colour === 'black' ? 'Black' : 'White';
}

/** Moves as written in a score, numbered: "2.d4 exd4 3.Qxd4", "2...Nc6 3.d4". */
function lineText(moves) {
  return moves
    .map((move, i) => {
      if (move.mover_is_white) return `${move.move_number}.${move.san}`;
      return i === 0 ? `${move.move_number}...${move.san}` : move.san;
    })
    .join(' ');
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
