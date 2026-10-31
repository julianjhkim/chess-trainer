/**
 * The start screen: one button per step.
 *
 * Clicking a step starts the session right there, with all four steps on: when
 * it is done the next one follows, and the step bar jumps anywhere at any time.
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
  sub.textContent = 'Pick a step to start with. The next one follows when it is done, and you can jump between them at any time.';

  const choices = document.createElement('div');
  choices.className = 'step-buttons';

  for (const step of session.steps) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'step-button';
    button.dataset.step = step.step;

    const num = document.createElement('span');
    num.className = 'choice-num';
    num.textContent = `${step.position}.`;

    const title = document.createElement('span');
    title.className = 'choice-title';
    title.textContent = step.title;

    const note = document.createElement('span');
    note.className = 'choice-note';
    note.textContent = NOTES[step.step] ?? '';

    button.append(num, title, note);
    button.addEventListener('click', () => begin(step.step));
    choices.append(button);
  }

  panel.append(heading, sub, choices);
  container.append(panel);

  async function begin(stepName) {
    const next = await withStatus('Starting…', () =>
      api.startSession(null, { startAt: stepName }),
    );
    set({ session: next });
    if (onStarted) onStarted(next);
  }
}
