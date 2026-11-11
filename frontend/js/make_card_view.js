/**
 * Make puzzles (step 2; internally `make_card`): paste one of my games and
 * the engine finds the puzzles in it.
 *
 * *Find puzzles* starts a scan in the background: Stockfish checks every move
 * of the game, both sides', and after each slip whose punishment is clear --
 * a forced line of two moves or more; after a mere inaccuracy, one that wins
 * material or mates -- it becomes a puzzle,
 * due the next day -- played as my opponent when the mistake was mine. The
 * page polls the scan for its progress (it can be stopped) and then lists
 * what was found -- the mistakes only, never a solution. Clicking one puts the
 * board on its position; ← / → step through the game. Mistakes with no clear
 * punishment are listed too, as not puzzles. Saving the first puzzles completes the step (and counts
 * the day); the form stays for the next game.
 */

import * as api from './api.js';
import { sleep } from './animate.js';
import { createBoard } from './board.js';
import { createMoveList } from './move_list.js';
import { bindArrowKeys, createMoveNav } from './move_nav.js';
import { set, setStatus } from './state.js';

const POLL_MS = 700;

export function renderMakeCardView(container, { step, onCompleted }) {
  container.replaceChildren();

  let destroyed = false;
  /** What was typed, kept across re-renders of the form. */
  const draft = { pgn: '', colour: '' };
  /** The latest scan as the server reports it. */
  let scan = { status: 'idle' };
  /** The puzzle picked in the list, by ply. */
  let selected = null;

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
  const resultCard = card_('Puzzles found', panelChanged);
  const movesCard = card_('Moves', panelChanged);
  resultCard.root.hidden = true;
  movesCard.root.hidden = true;
  side.append(formCard.root, resultCard.root, movesCard.root);

  layout.append(boardColumn, side);
  container.append(layout);

  const board = createBoard({ orientation: 'white', interactive: false });
  boardAndBar.append(board.element);
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
  setStatus('Paste one of your games to find the puzzles in it.');
  void resume();

  // -- the scan ----------------------------------------------------------
  /** Coming back to the step: pick up a scan still running, or its outcome. */
  async function resume() {
    try {
      const state = await api.scanState();
      if (destroyed) return;
      if (state.status !== 'idle') show(state);
      if (state.status === 'running') void poll();
    } catch {
      // Nothing to pick up: the form is already there.
    }
  }

  async function findPuzzles() {
    if (!draft.pgn.trim()) return renderForm({ error: 'Paste a game first.' });
    try {
      show(await api.startScan({ pgn: draft.pgn, colour: draft.colour || null }));
    } catch (error) {
      renderForm({ error: error.message });
      setStatus(error.message, 'error');
      return;
    }
    await poll();
  }

  async function poll() {
    while (!destroyed && scan.status === 'running') {
      await sleep(POLL_MS);
      if (destroyed) return;
      try {
        show(await api.scanState());
      } catch (error) {
        setStatus(error.message, 'error');
        return;
      }
    }
  }

  async function stopScan() {
    show(await api.cancelScan());
  }

  /** Draw a scan state: progress while running, the outcome once done. */
  function show(state) {
    const wasRunning = scan.status === 'running';
    scan = state;
    renderForm();
    buildControls();
    if (state.status === 'running') {
      setStatus(`Checking your moves… ${state.done} of ${state.total}`);
      return;
    }
    if (state.status === 'done') {
      if (state.session) set({ session: state.session });
      if (state.streak) set({ streak: state.streak });
      if (state.session && onCompleted) onCompleted(state.session, { rerender: false });
      if (wasRunning || selected === null) selected = state.found[0]?.ply ?? null;
      renderResult();
      showGame();
      setStatus(summaryText(state));
    } else if (state.status === 'failed') {
      setStatus(`The scan failed: ${state.error}`, 'error');
    } else if (state.status === 'cancelled') {
      setStatus('Stopped. Nothing was saved.');
    }
  }

  // -- panels ------------------------------------------------------------
  function renderForm({ error = null } = {}) {
    const running = scan.status === 'running';
    const body = document.createElement('div');
    body.className = 'new-card';
    body.append(
      paragraph(
        'Paste one of your games. Stockfish checks every move, yours and your opponent’s; wherever a slip has a clear punishment, that becomes a puzzle — played as your opponent when the slip was yours.',
        'choice-note',
      ),
    );

    const textarea = document.createElement('textarea');
    textarea.rows = 6;
    textarea.spellcheck = false;
    textarea.placeholder = '[White "..."]\n[Black "..."]\n\n1. e4 e5 2. Nf3 ...';
    textarea.value = draft.pgn;
    textarea.disabled = running;
    textarea.setAttribute('aria-label', 'PGN');
    textarea.addEventListener('input', () => {
      draft.pgn = textarea.value;
    });

    const fields = document.createElement('div');
    fields.className = 'new-card-fields';
    const colourLabel = document.createElement('label');
    colourLabel.append('You played');
    const colour = document.createElement('select');
    colour.setAttribute('aria-label', 'Your colour');
    colour.disabled = running;
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
    fields.append(colourLabel);

    const row = document.createElement('div');
    row.className = 'button-row';
    if (running) {
      row.append(button('Stop', stopScan));
    } else {
      row.append(button('Find puzzles', findPuzzles, 'primary'));
    }
    body.append(textarea, fields, row);

    if (running) body.append(progressBar(scan.done, scan.total));
    if (error) body.append(paragraph(error, 'paste-error'));
    if (scan.status === 'failed') body.append(paragraph(`The scan failed: ${scan.error}`, 'paste-error'));
    formCard.setBody(body);
  }

  function renderResult() {
    const body = document.createElement('div');
    body.append(paragraph(summaryText(scan), 'result-headline'));
    if (scan.found.length) {
      const list = document.createElement('ul');
      list.className = 'found-list';
      for (const found of scan.found) {
        const item = document.createElement('li');
        const pick = document.createElement('button');
        pick.type = 'button';
        pick.className = 'found-puzzle';
        if (found.ply === selected) pick.classList.add('selected');
        const side = found.solver_colour === 'white' ? 'White' : 'Black';
        const moves = `${found.solver_moves} move${found.solver_moves === 1 ? '' : 's'}`;
        const cost = `${found.classification} (−${found.win_percent_drop.toFixed(1)}%)`;
        pick.textContent = found.slip_mine
          ? `${found.move_label}, your ${cost}: punish it as ${side}, ${moves}`
          : `${found.move_label}, their ${cost}: punish it, ${moves}`;
        pick.addEventListener('click', () => {
          selected = found.ply;
          renderResult();
          nav.go(found.ply);
        });
        const note = document.createElement('span');
        note.className = 'choice-note';
        note.textContent = found.created
          ? ` · first due ${found.due_on}`
          : found.restored
            ? ' · restored'
            : ' · already a puzzle';
        item.append(pick, note);
        list.append(item);
      }
      body.append(list);
    }
    if (scan.skipped.length) {
      body.append(
        paragraph(
          `Not puzzles (no clear punishment of two moves or more — after an inaccuracy, one that wins material or mates): ${scan.skipped.join(', ')}.`,
          'choice-note',
        ),
      );
    }
    resultCard.setBody(body);
    resultCard.root.hidden = false;
    panelChanged();
  }

  function buildControls() {
    controls.replaceChildren();
    if (scan.status === 'done') controls.append(button('Flip board', () => board.flip()));
    panelChanged();
  }

  // -- the board ---------------------------------------------------------
  function showGame() {
    const moves = scan.moves ?? [];
    board.setOrientation(scan.colour ?? 'white');
    nav.setMoves(moves, { index: selected ?? moves.length });
    moveList.setMoves(moves, { marked: selected });
    movesCard.root.hidden = false;
    navRow.hidden = false;
    navReady = true;
    panelChanged();
    onNavChange(nav.view());
  }

  function onNavChange(view) {
    latestView = view;
    moveList.setCurrent(view.index);
    drawing = drawing
      .then(() => (view === latestView ? drawView(view) : null))
      .catch((error) => setStatus(error.message, 'error'));
  }

  /** A puzzle's position is right after the mistake, which is highlighted. */
  async function drawView(view) {
    if (destroyed || !view.fen) return;
    await board.setFen(view.fen, { lastMove: squares(view.lastMove) });
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
function summaryText(state) {
  const n = state.found?.length ?? 0;
  if (!n) return 'No puzzles in this game: no slip had a clear punishment.';
  const fresh = state.found.filter((found) => found.created || found.restored).length;
  const saved = fresh === n ? 'saved' : `${fresh} new`;
  return `Found ${n} puzzle${n === 1 ? '' : 's'} in this game — ${saved}. Play them in step 1, “Puzzles”, from tomorrow.`;
}

function progressBar(done, total) {
  const box = document.createElement('div');
  box.className = 'scan-progress';
  const bar = document.createElement('progress');
  bar.max = Math.max(total, 1);
  bar.value = done;
  const text = paragraph(`Checking your moves… ${done} of ${total}`, 'choice-note');
  box.append(bar, text);
  return box;
}

function squares(uci) {
  return uci ? [uci.slice(0, 2), uci.slice(2, 4)] : undefined;
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
