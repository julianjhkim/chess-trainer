/**
 * Thin wrapper over the local HTTP API.
 *
 * Every call goes to our own origin; the app makes no external requests at
 * runtime, which is why the frontend libraries are vendored.
 */

async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  if (response.status === 204) return null;
  return response.json();
}

async function errorMessage(response) {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const payload = await response.json();
    if (payload && payload.detail) {
      detail = typeof payload.detail === 'string'
        ? payload.detail
        : JSON.stringify(payload.detail);
    }
  } catch {
    /* response had no JSON body; keep the status text */
  }
  return detail;
}

// -- health ---------------------------------------------------------------
export const getHealth = () => request('/api/health');

// -- session --------------------------------------------------------------
export const getSession = () => request('/api/session');
export const startSession = (steps) =>
  request('/api/session/start', { method: 'POST', body: { steps: steps ?? null } });
export const resetSession = () => request('/api/session/reset', { method: 'POST' });
export const jumpToStep = (step) => request(`/api/session/jump/${step}`, { method: 'POST' });
export const completeStep = (step) => request(`/api/session/complete/${step}`, { method: 'POST' });

// -- streak ---------------------------------------------------------------
export const getStreak = () => request('/api/streak');

// -- board rules ----------------------------------------------------------
export const boardState = (fen) => request('/api/board/state', { method: 'POST', body: { fen } });
export const playMove = (fen, from, to, promotion) =>
  request('/api/board/move', { method: 'POST', body: { fen, from, to, promotion } });

// -- engine ---------------------------------------------------------------
export const evaluate = (fen, depth) =>
  request('/api/engine/eval', { method: 'POST', body: { fen, depth: depth ?? null } });

// -- games ----------------------------------------------------------------
export const latestGame = () => request('/api/game/latest');
export const fetchLatestGame = () => request('/api/game/fetch-latest', { method: 'POST' });
export const setGameBaseline = () => request('/api/game/baseline', { method: 'POST' });
export const pollForNewGame = (budgetSeconds) =>
  request('/api/game/poll-new', {
    method: 'POST',
    body: { budget_seconds: budgetSeconds ?? null },
  });
export const pastePgn = (pgn) => request('/api/game/paste', { method: 'POST', body: { pgn } });

// -- review ---------------------------------------------------------------
export const startReview = (step, { gameId = null, restart = false } = {}) =>
  request('/api/review/start', {
    method: 'POST',
    body: { step, game_id: gameId, restart },
  });
export const reviewState = (step) => request(`/api/review/${step}`);
export const reviewAttempt = (step, from, to, promotion) =>
  request('/api/review/attempt', {
    method: 'POST',
    body: { step, from, to, promotion },
  });
export const reviewShowAnswer = (step) =>
  request('/api/review/show-answer', { method: 'POST', body: { step } });
export const reviewAcknowledge = (step) =>
  request('/api/review/acknowledge', { method: 'POST', body: { step } });
