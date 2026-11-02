/**
 * Make a revision card (step 2): pick a slip from one of my games.
 *
 * Paste a game's PGN and type the number of my move that went wrong ("9" for
 * my ninth move, White or Black). *Show position* puts the board on the
 * position before it, with that move as a red arrow; ← / → (or the buttons
 * and the move list) step through the moves leading there. *Save card* asks
 * Stockfish for the answer -- never shown here -- and schedules the card for
 * the next day. The first card saved completes the step (and counts the day);
 * the step stays open for more, and the step bar moves on.
 */

import * as api from './api.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { createMoveList } from './move_list.js';
import { bindArrowKeys, createMoveNav } from './move_nav.js';
import { set, setStatus, withStatus } from './state.js';

export function renderMakeCardView(container, { step, onCompleted }) {
  container.replaceChildren();

  let destroyed = false;
  /** What was typed, kept across re-renders of the form. */
  const draft = { pgn: '', moveNumber: '', colour: '' };
  /** The position the typed move gives, once shown. */
  let preview = null;
  /** The last card saved, for the confirmation line. */
  let saved = null;

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
  boardColumn.append(boardAndBar, navRow, controls);

  const side = document.createElement('div');
  side.className = 'side-panel';
  const formCard = card_(step.title, panelChanged);
  const movesCard = card_('Moves', panelChanged);
  movesCard.root.hidden = true;
  side.append(formCard.root, movesCard.root);

  layout.append(boardColumn, side);
  container.append(layout);

  const evalBar = createEvalBar();
  const board = createBoard({ orientation: 'white', interactive: false });
  boardAndBar.append(board.element, evalBar.element);
  board.refresh();

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

  renderForm();
  buildControls();
  setStatus('Paste a game and give the move you got wrong.');

  // -- the form ----------------------------------------------------------
  function renderForm({ error = null } = {}) {
    const body = document.createElement('div');
    body.className = 'new-card';

    if (saved) body.append(paragraph(savedText(saved), 'card-added'));

    body.append(
      paragraph(
        'Paste the game, then type the number of the move you got wrong — "9" for your 9th move, as White or Black.',
        'choice-note',
      ),
    );
    const textarea = document.createElement('textarea');
    textarea.rows = 6;
    textarea.spellcheck = false;
    textarea.placeholder = '[White "..."]\n[Black "..."]\n\n1. e4 e5 2. Nf3 ...';
    textarea.value = draft.pgn;
    textarea.setAttribute('aria-label', 'PGN');
    textarea.addEventListener('input', () => {
      draft.pgn = textarea.value;
    });

    const fields = document.createElement('div');
    fields.className = 'new-card-fields';
    const numberLabel = document.createElement('label');
    numberLabel.append('Your move number');
    const number = document.createElement('input');
    number.type = 'number';
    number.min = '1';
    number.value = draft.moveNumber;
    number.setAttribute('aria-label', 'Move number');
    number.addEventListener('input', () => {
      draft.moveNumber = number.value;
    });
    number.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') void runPreview();
    });
    numberLabel.append(number);

    const colourLabel = document.createElement('label');
    colourLabel.append('You played');
    const colour = document.createElement('select');
    colour.setAttribute('aria-label', 'Your colour');
    for (const [value, text] of [['', 'Auto (from your names)'], ['white', 'White'], ['black', 'Black']]) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      colour.append(option);
    }
    colour.value = draft.colour;
    colour.addEventListener('change', () => {
      draft.colour = colour.value;
    });
    colourLabel.append(colour);
    fields.append(numberLabel, colourLabel);

    const row = document.createElement('div');
    row.className = 'button-row';
    row.append(button('Show position', runPreview));
    body.append(textarea, fields, row);

    if (error) body.append(paragraph(error, 'paste-error'));
    if (preview) body.append(previewNote(preview));
    formCard.setBody(body);
  }

  function request() {
    return {
      pgn: draft.pgn,
      move_number: Number.parseInt(draft.moveNumber, 10),
      colour: draft.colour || null,
    };
  }

  async function runPreview() {
    const payload = request();
    if (!draft.pgn.trim()) return renderForm({ error: 'Paste a game first.' });
    if (!(payload.move_number >= 1)) return renderForm({ error: 'Type the number of your move.' });
    try {
      preview = await withStatus('Finding the position…', () => api.previewInaccuracyCard(payload));
    } catch (error) {
      preview = null;
      hideNav();
      buildControls();
      renderForm({ error: error.message });
      setStatus(error.message, 'error');
      return;
    }
    if (destroyed) return;
    saved = null;
    board.setOrientation(preview.colour);
    renderForm();
    buildControls();
    showNav(preview.moves);
    setStatus(`You played ${preview.move_label} here — the red arrow. Save the card to drill it.`);
  }

  async function saveCard() {
    if (!preview) return;
    const made = await withStatus('Asking Stockfish for the answer…', () =>
      api.createInaccuracyCard(request()),
    );
    if (made.session) set({ session: made.session });
    if (made.streak) set({ streak: made.streak });
    if (made.session && onCompleted) onCompleted(made.session, { rerender: false });
    saved = made;
    preview = null;
    draft.moveNumber = '';
    hideNav();
    buildControls();
    renderForm();
    setStatus(savedText(made));
  }

  function savedText(made) {
    if (made.restored) return `Restored the card for ${made.move_label} you had deleted — due ${made.due_on}.`;
    if (!made.created) return `You already had a card for ${made.move_label} — it is now due ${made.due_on}.`;
    return `Card saved for ${made.move_label} — first due ${made.due_on}.`;
  }

  function previewNote(shown) {
    const box = document.createElement('div');
    const sideName = shown.colour === 'white' ? 'White' : 'Black';
    box.append(
      playedLine(shown.move_label),
      paragraph(
        `You had ${sideName}${shown.opponent ? ` against ${shown.opponent}` : ''}. ← → step through the moves before it.`,
        'choice-note',
      ),
    );
    if (shown.existing === 'active') {
      box.append(paragraph('You already have a card for this position: saving brings it back to tomorrow.', 'choice-note'));
    } else if (shown.existing === 'deleted') {
      box.append(paragraph('You deleted a card for this position before: saving restores it.', 'choice-note'));
    }
    return box;
  }

  function buildControls() {
    controls.replaceChildren();
    if (preview) controls.append(button('Save card', saveCard, 'primary'));
    controls.append(button('Flip board', () => board.flip()));
    panelChanged();
  }

  // -- drawing -----------------------------------------------------------
  function showNav(moves) {
    nav.setMoves(moves, { index: moves.length });
    moveList.setMoves(moves);
    moveList.setCurrent(moves.length);
    movesCard.root.hidden = false;
    navRow.hidden = false;
    navReady = true;
    panelChanged();
    onNavChange(nav.view());
  }

  function hideNav() {
    navReady = false;
    nav.setMoves([], { index: 0 });
    movesCard.root.hidden = true;
    navRow.hidden = true;
    board.setShapes([]);
    board.setHighlights([]);
    panelChanged();
  }

  function onNavChange(view) {
    latestView = view;
    moveList.setCurrent(view.index);
    drawing = drawing
      .then(() => (view === latestView ? drawView(view) : null))
      .catch((error) => setStatus(error.message, 'error'));
  }

  /** At the slip position the move I played is a red arrow; elsewhere nothing. */
  async function drawView(view) {
    if (!preview || destroyed) return;
    const atSlip = view.index === nav.length;
    const fen = atSlip ? preview.fen : (view.fen ?? preview.fen);
    const lastMove = atSlip ? preview.last_move_uci : view.lastMove;
    board.setHighlights([]);
    await board.setFen(fen, { lastMove: squares(lastMove) });
    if (view !== latestView || destroyed || !preview) return;
    board.setHighlights(atSlip ? [arrow(preview.my_move_uci, 'red')] : []);
    void refreshEval(fen);
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

  /** Panels beside and under the board change size; chessground must re-measure. */
  function panelChanged() {
    board.refresh();
  }

  return {
    destroy() {
      destroyed = true;
      unbindKeys();
      board.destroy();
    },
  };
}

// -- small DOM helpers ----------------------------------------------------
/** "You played 2.Nf3 here. The red arrow shows it." */
function playedLine(moveLabel) {
  const element = paragraph('', 'played-line');
  element.append('You played ');
  const move = document.createElement('strong');
  move.textContent = moveLabel;
  element.append(move, ' here. The red arrow shows it.');
  return element;
}

function squares(uci) {
  return uci ? [uci.slice(0, 2), uci.slice(2, 4)] : undefined;
}

function arrow(uci, brush) {
  return { orig: uci.slice(0, 2), dest: uci.slice(2, 4), brush };
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
