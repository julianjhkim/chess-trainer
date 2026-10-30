/**
 * The play step (step 2).
 *
 * Two buttons: open chess.com, and "I'm done — fetch my game". Fetching polls
 * the archive for a game newer than the one we saw before you left, because the
 * API can lag a minute or two behind a finished game. After about two minutes a
 * PGN paste box appears as a fallback.
 *
 * Finishing this step hands straight over to step 3.
 */

import * as api from './api.js';
import { createPgnPaste } from './pgn_paste.js';
import { set, setStatus, withStatus } from './state.js';

const CHESSCOM_PLAY_URL = 'https://www.chess.com/play/online';
const TOTAL_BUDGET_MS = 120_000;
const WINDOW_SECONDS = 12;

export function renderPlayView(container, { step, onCompleted }) {
  container.replaceChildren();

  let destroyed = false;
  let polling = false;
  let baseline = null;

  const panel = document.createElement('section');
  panel.className = 'panel';

  const heading = document.createElement('h2');
  heading.textContent = 'Play a game on chess.com';

  const sub = document.createElement('p');
  sub.className = 'sub';
  sub.textContent =
    'Play your game, then come back and fetch it. It will be reviewed in the next step.';

  const baselineNote = document.createElement('p');
  baselineNote.className = 'choice-note';
  baselineNote.textContent = 'Checking which game is your most recent…';

  const row = document.createElement('div');
  row.className = 'button-row';

  const openButton = document.createElement('button');
  openButton.type = 'button';
  openButton.textContent = 'Open chess.com ↗';
  openButton.addEventListener('click', () => {
    window.open(CHESSCOM_PLAY_URL, '_blank', 'noopener');
    setStatus('chess.com opened in a new tab.');
  });

  const fetchButton = document.createElement('button');
  fetchButton.type = 'button';
  fetchButton.className = 'primary';
  fetchButton.textContent = "I'm done — fetch my game";
  fetchButton.addEventListener('click', () => {
    pollForGame().catch((error) => setStatus(error.message, 'error'));
  });

  row.append(openButton, fetchButton);

  const progress = document.createElement('div');
  progress.className = 'poll-progress';
  progress.hidden = true;

  const progressBar = document.createElement('div');
  progressBar.className = 'progress';
  const progressFill = document.createElement('div');
  progressFill.className = 'progress-fill';
  progressBar.append(progressFill);

  const progressText = document.createElement('p');
  progressText.className = 'choice-note';
  progressText.style.margin = '8px 0 0';

  progress.append(progressBar, progressText);

  const paste = createPgnPaste({
    summary: 'Paste the PGN instead',
    hint: 'If the game has not appeared yet, open it on chess.com, choose Share → PGN, and paste it here.',
    onSubmit: async (pgn) => {
      const result = await api.pastePgn(pgn);
      // Name the game explicitly for step 3: a pasted PGN may carry no date,
      // and the review step otherwise picks the most recently *played* game.
      set({ pendingGameId: result.game.id });
      await finish(result.game);
    },
  });

  panel.append(heading, sub, baselineNote, row, progress, paste.element);
  container.append(panel);

  establishBaseline();

  // -- behaviour ---------------------------------------------------------
  async function establishBaseline() {
    try {
      const result = await api.setGameBaseline();
      if (destroyed) return;
      baseline = result.game;
      baselineNote.textContent = baseline
        ? `Your latest game so far: vs ${baseline.opponent ?? 'unknown'}. Anything newer counts as today's game.`
        : 'Could not reach chess.com just now — the next game found will be used.';
    } catch (error) {
      if (destroyed) return;
      baselineNote.textContent = `Could not reach chess.com (${error.message}). The next game found will be used.`;
    }
  }

  async function pollForGame() {
    if (polling) return;
    polling = true;
    fetchButton.disabled = true;
    progress.hidden = false;
    paste.element.open = false;

    const startedAt = Date.now();
    let attempts = 0;

    try {
      while (!destroyed) {
        const elapsed = Date.now() - startedAt;
        if (elapsed >= TOTAL_BUDGET_MS) break;

        updateProgress(elapsed, attempts);
        const result = await api.pollForNewGame(WINDOW_SECONDS);
        attempts += result.attempts;

        if (destroyed) return;
        if (result.found) {
          updateProgress(TOTAL_BUDGET_MS, attempts);
          progressText.textContent = `Found it — vs ${result.game.opponent ?? 'unknown'}.`;
          setStatus('Game found.');
          set({ pendingGameId: result.game.id });
          await finish(result.game);
          return;
        }
        if (result.error) {
          progressText.textContent = `chess.com said: ${result.error} — still trying…`;
        }
      }

      if (destroyed) return;
      progressText.textContent =
        'No new game appeared in two minutes. The archive can lag — try again, or paste the PGN below.';
      setStatus('No new game found yet.', 'busy');
      paste.focus();
    } finally {
      polling = false;
      fetchButton.disabled = false;
    }
  }

  function updateProgress(elapsedMs, attempts) {
    const fraction = Math.min(1, elapsedMs / TOTAL_BUDGET_MS);
    progressFill.style.width = `${Math.round(fraction * 100)}%`;
    const remaining = Math.max(0, Math.ceil((TOTAL_BUDGET_MS - elapsedMs) / 1000));
    progressText.textContent = `Watching the chess.com archive — ${remaining}s left (${attempts} check${attempts === 1 ? '' : 's'}).`;
  }

  /** Mark step 2 done, which advances the session to the review step. */
  async function finish(game) {
    const result = await withStatus('Saving…', () => api.completeStep(step.step));
    set({ session: result.session, streak: result.streak });
    setStatus(`Fetched your game vs ${game?.opponent ?? 'unknown'} — on to the review.`);
    if (onCompleted) onCompleted(result.session);
  }

  return {
    destroy() {
      destroyed = true;
    },
  };
}
