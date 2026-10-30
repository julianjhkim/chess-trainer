/**
 * Application entry point: wires the top bar, router and status line together,
 * and loads the initial session, streak and health state.
 */

import * as api from './api.js';
import { boards } from './board.js';
import { createRouter } from './router.js';
import { get, set, setStatus, subscribe } from './state.js';
import { createStepBar } from './stepbar.js';
import { createStreakView } from './streak_view.js';

const view = document.getElementById('view');
const statusLine = document.getElementById('status');
const engineInfo = document.getElementById('engine-info');

const streakView = createStreakView(document.getElementById('streak'));
const stepBar = createStepBar(document.getElementById('stepbar'), {
  onJump: (session) => router.render(session),
});
const router = createRouter(view, {
  onStarted: (session) => router.render(session),
  onCompleted: (session) => router.render(session),
});

// Re-render the chrome whenever state changes. The main view re-renders only
// on explicit navigation, so an eval update does not rebuild the board.
subscribe((state) => {
  stepBar.render(state.session);
  streakView.render(state.streak);
  statusLine.textContent = state.status.text;
  statusLine.className = `status ${state.status.kind}`;
});

async function boot() {
  try {
    const [session, streak, health] = await Promise.all([
      api.getSession(),
      api.getStreak(),
      api.getHealth(),
    ]);
    set({ session, streak, health });
    renderEngineInfo(health);
    router.render(session);
  } catch (error) {
    view.replaceChildren();
    const panel = document.createElement('section');
    panel.className = 'panel';
    const heading = document.createElement('h2');
    heading.textContent = 'Could not reach the server';
    const message = document.createElement('p');
    message.className = 'sub';
    message.textContent = error.message;
    panel.append(heading, message);
    view.append(panel);
    setStatus(error.message, 'error');
  }
}

function renderEngineInfo(health) {
  const engine = health.engine ?? {};
  const parts = [`v${health.version}`];
  parts.push(engine.exists ? `Stockfish depth ${engine.depth}` : 'Stockfish NOT FOUND');
  parts.push(`${health.chesscom_username}@chess.com`);
  parts.push(health.lichess_token_present ? 'Lichess token set' : 'No Lichess token');
  engineInfo.textContent = parts.join('  ·  ');
  engineInfo.title = `Engine: ${engine.path ?? 'unknown'}\nDatabase: ${health.database}\nStreak timezone: ${health.timezone}`;
}

boot();

// Exposed for debugging from the browser console.
window.chessTrainer = { api, state: get, boards };
