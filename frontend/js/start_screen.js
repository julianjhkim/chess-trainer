/**
 * The start screen: four checkboxes (all checked) and a Start button.
 *
 * Checked steps run in order. Unchecking everything disables Start, since an
 * empty session has nothing to do.
 */

import * as api from './api.js';
import { set, withStatus } from './state.js';

const NOTES = {
  review_last_game: 'Analyse your most recent chess.com game',
  play: 'Open chess.com, then fetch the game you just played',
  review_new_game: 'Analyse the game you just played',
  cards: 'Opening drills from the Lichess masters database',
};

export function renderStartScreen(container, { session, onStarted }) {
  container.replaceChildren();

  const panel = document.createElement('section');
  panel.className = 'panel';

  const heading = document.createElement('h2');
  heading.textContent = "Today's session";

  const sub = document.createElement('p');
  sub.className = 'sub';
  sub.textContent = 'Pick the steps to run. They run in this order, and you can jump between them at any time.';

  const choices = document.createElement('div');
  choices.className = 'step-choices';

  const boxes = new Map();
  for (const step of session.steps) {
    const label = document.createElement('label');
    label.className = 'choice';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = true;
    box.addEventListener('change', updateStartButton);
    boxes.set(step.step, box);

    const num = document.createElement('span');
    num.className = 'choice-num';
    num.textContent = `${step.position}.`;

    const title = document.createElement('span');
    title.className = 'choice-title';
    title.textContent = step.title;

    const note = document.createElement('span');
    note.className = 'choice-note';
    note.textContent = NOTES[step.step] ? `— ${NOTES[step.step]}` : '';

    label.append(box, num, title, note);
    choices.append(label);
  }

  const row = document.createElement('div');
  row.className = 'button-row';

  const start = document.createElement('button');
  start.className = 'primary';
  start.textContent = 'Start';
  start.addEventListener('click', onStart);

  const hint = document.createElement('span');
  hint.className = 'choice-note';

  row.append(start, hint);
  panel.append(heading, sub, choices, row);
  container.append(panel);

  function selected() {
    return [...boxes.entries()].filter(([, box]) => box.checked).map(([name]) => name);
  }

  function updateStartButton() {
    const count = selected().length;
    start.disabled = count === 0;
    hint.textContent = count === 0 ? 'Select at least one step.' : '';
  }

  async function onStart() {
    const steps = selected();
    const next = await withStatus('Starting session…', () => api.startSession(steps));
    set({ session: next });
    if (onStarted) onStarted(next);
  }

  updateStartButton();
}
