/**
 * Temporary Phase 1 scaffold.
 *
 * Each step gets a playable board with a live eval bar, so the board, the
 * engine round-trip, the step bar and the streak can all be exercised before
 * the real step views exist. Phase 2 replaces this for the review and play
 * steps, Phase 3 for the opening cards; this module goes away with them.
 */

import * as api from './api.js';
import { createBoard } from './board.js';
import { createEvalBar } from './evalbar.js';
import { set, setStatus, withStatus } from './state.js';

export function renderPlaceholder(container, { session, step, onCompleted }) {
  container.replaceChildren();

  const layout = document.createElement('div');
  layout.className = 'board-layout';

  const boardColumn = document.createElement('div');
  boardColumn.className = 'board-column';

  const boardAndBar = document.createElement('div');
  boardAndBar.className = 'board-and-bar';

  const evalBar = createEvalBar();
  const board = createBoard({ onMove: handleMove });

  boardAndBar.append(board.element, evalBar.element);

  const controls = document.createElement('div');
  controls.className = 'button-row';

  const flip = button('Flip board', () => board.flip());
  const reset = button('Reset position', async () => {
    await board.setFen(board.START_FEN);
    await refreshEval();
  });
  controls.append(flip, reset);
  boardColumn.append(boardAndBar, controls);

  // -- side panel --------------------------------------------------------
  const side = document.createElement('div');
  side.className = 'side-panel';

  const info = document.createElement('div');
  info.className = 'card';
  const infoTitle = document.createElement('h3');
  infoTitle.textContent = `Step ${step.position}`;
  const stepName = document.createElement('p');
  stepName.style.margin = '0 0 10px';
  stepName.style.fontWeight = '600';
  stepName.textContent = step.title;
  const note = document.createElement('p');
  note.className = 'placeholder-note';
  note.textContent = PLACEHOLDER_NOTES[step.step] ?? 'Not built yet.';
  info.append(infoTitle, stepName, note);

  const moves = document.createElement('div');
  moves.className = 'card';
  const movesTitle = document.createElement('h3');
  movesTitle.textContent = 'Moves played';
  const movesList = document.createElement('p');
  movesList.className = 'mono';
  movesList.style.margin = '0';
  movesList.style.wordBreak = 'break-word';
  movesList.textContent = '—';
  moves.append(movesTitle, movesList);

  const done = document.createElement('div');
  done.className = 'card';
  const doneTitle = document.createElement('h3');
  doneTitle.textContent = 'Streak';
  const doneNote = document.createElement('p');
  doneNote.className = 'choice-note';
  doneNote.style.margin = '0 0 10px';
  doneNote.textContent = 'Completing any step counts today towards the streak.';
  const completeButton = button('Mark this step complete', complete, 'primary');
  done.append(doneTitle, doneNote, completeButton);

  side.append(info, moves, done);
  layout.append(boardColumn, side);
  container.append(layout);

  const played = [];

  // -- behaviour ---------------------------------------------------------
  async function handleMove(result) {
    played.push(result.san);
    movesList.textContent = played.join(' ');
    await refreshEval();
  }

  async function refreshEval() {
    evalBar.pending();
    try {
      const response = await api.evaluate(board.getFen());
      evalBar.update(response.evaluation);
      setStatus(response.cached ? 'Evaluation from cache' : `Analysed at depth ${response.depth}`);
    } catch (error) {
      evalBar.clear();
      setStatus(error.message, 'error');
    }
  }

  async function complete() {
    completeButton.disabled = true;
    const result = await withStatus('Saving…', () => api.completeStep(step.step));
    set({ session: result.session, streak: result.streak });
    if (onCompleted) onCompleted(result.session);
  }

  // Initial position and evaluation.
  board.setFen(board.START_FEN).then(refreshEval);

  return { destroy: () => board.destroy() };
}

const PLACEHOLDER_NOTES = {
  review_last_game: 'Phase 2 will replay your last chess.com game up to your first inaccuracy and ask you to find the better move. For now this is a free board so the board, eval bar and engine can be checked.',
  play: 'Phase 2 will add the "Open chess.com" and "I\'m done — fetch my game" buttons here.',
  review_new_game: 'Phase 2 will review the game you just played, the same way as step 1.',
  cards: 'Phase 3 will add the opening card drills from the Lichess masters database.',
};

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
