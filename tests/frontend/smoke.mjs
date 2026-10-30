/**
 * Frontend smoke test: runs the real frontend modules in a DOM against a
 * running server, so chessground, the board round-trip, the eval bar, the step
 * bar and the start screen are all exercised rather than merely parsed.
 *
 * Needs the server up:
 *     chess-trainer --no-browser --port 8791
 *     npm install && npm run smoke
 *
 * Override the target with CHESS_TRAINER_URL.
 */

import { JSDOM } from 'jsdom';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.CHESS_TRAINER_URL ?? 'http://127.0.0.1:8791';
const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend');

const dom = new JSDOM('<!doctype html><html><body><div id="app"></div></body></html>', {
  url: BASE, pretendToBeVisual: true,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.Node = dom.window.Node;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
globalThis.cancelAnimationFrame = clearTimeout;
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);

// api.js uses root-relative paths; point them at the running server.
const realFetch = globalThis.fetch;
globalThis.fetch = (url, opts) =>
  realFetch(typeof url === 'string' && url.startsWith('/') ? BASE + url : url, opts);

try {
  const probe = await fetch(`${BASE}/api/health`);
  if (!probe.ok) throw new Error(`HTTP ${probe.status}`);
} catch (error) {
  console.error(`Cannot reach ${BASE} (${error.message}).`);
  console.error('Start the server first:  chess-trainer --no-browser --port 8791');
  process.exit(2);
}

let failures = 0;
const check = (name, cond, extra = '') => {
  console.log(`${cond ? '  PASS' : '  FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
  if (!cond) failures++;
};

// ---- chessground renders -------------------------------------------------
const { Chessground } = await import(`${REPO}/vendor/chessground/chessground.js`);
const host = document.getElementById('app');
const ground = Chessground(host, { fen: 'start' });
const squares = host.querySelectorAll('cg-board square, cg-board piece');
check('chessground mounts', host.querySelector('cg-container') !== null);
const realPieces = (el) => [...el.querySelectorAll('piece')].filter(p => !p.classList.contains('ghost'));
check('chessground renders 32 pieces', realPieces(host).length === 32, `found ${realPieces(host).length}`);
check('orientation defaults to white', ground.state.orientation === 'white');
ground.toggleOrientation();
check('flip works', ground.state.orientation === 'black');
ground.destroy();

// ---- eval bar ------------------------------------------------------------
const { createEvalBar } = await import(`${REPO}/js/evalbar.js`);
const bar = createEvalBar();
check('eval bar starts pending', bar.element.querySelector('.evalbar-number').textContent === '—');
bar.update({ text: '+0.45', fraction: 0.541 });
const num = bar.element.querySelector('.evalbar-number');
const whiteFill = bar.element.querySelector('.evalbar-white');
check('eval bar shows the number', num.textContent === '+0.45');
check('eval bar fills proportionally', parseFloat(whiteFill.style.height).toFixed(1) === '54.1', whiteFill.style.height);
check('eval bar clears pending class', !num.classList.contains('pending'));
bar.update({ text: 'M3', fraction: 0.98 });
check('eval bar shows mate', num.textContent === 'M3');

// ---- api.js against the real server -------------------------------------
const api = await import(`${REPO}/js/api.js`);
const stateModule = await import(`${REPO}/js/state.js`);
const health = await api.getHealth();
check('api.getHealth works', health.status === 'ok', `v${health.version}`);
const state = await api.boardState();
check('api.boardState returns dests', state.dests.e2.includes('e4'));
const moved = await api.playMove(state.fen, 'e2', 'e4');
check('api.playMove returns SAN', moved.san === 'e4');
try {
  await api.playMove(state.fen, 'e2', 'e5');
  check('illegal move rejected', false, 'no error thrown');
} catch (e) {
  check('illegal move rejected with message', /not legal/.test(e.message), e.message);
}

// ---- board.js: full round trip, user move + auto-replay -----------------
const { createBoard } = await import(`${REPO}/js/board.js`);
const moveLog = [];
const board = createBoard({ onMove: (r) => { moveLog.push(r.san); } });
document.body.append(board.element);
await board.setFen(board.START_FEN);
check('board.setFen renders pieces', realPieces(board.element).length === 32, `found ${realPieces(board.element).length}`);
check('board exposes the start FEN', board.getFen().startsWith('rnbqkbnr'));

const r1 = await board.pushMove('e2e4');
check('board.pushMove plays a move', r1.san === 'e4');
check('board FEN advanced', board.getFen().includes(' b '));
await board.pushMove('e7e5');
await board.pushMove('g1f3');
check('auto-replay of 3 moves lands correctly',
      board.getFen().startsWith('rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2'), board.getFen().split(' ')[0]);

board.setShapes([{ orig: 'b8', dest: 'c6', brush: 'green' }]);
check('board accepts arrow shapes', board.ground.state.drawable.shapes.length === 1);
check('board starts oriented white', board.orientation() === 'white', board.orientation());
board.flip();
check('board flip works', board.orientation() === 'black', board.orientation());
board.flip();
check('board flips back', board.orientation() === 'white');
board.setOrientation('black');
check('setOrientation works', board.orientation() === 'black');

// Orientation passed at construction must be honoured (review orients to my colour).
const blackBoard = createBoard({ orientation: 'black' });
check('createBoard honours the orientation option', blackBoard.orientation() === 'black', blackBoard.orientation());
blackBoard.destroy();
board.setInteractive(false);
check('board can be made non-interactive', board.ground.state.draggable.enabled === false);

// ---- engine eval through the frontend path ------------------------------
const evaluation = await api.evaluate(board.getFen());
check('engine eval returns a formatted string', /^[+−]?\d+\.\d\d$|^[−]?M\d+$/.test(evaluation.evaluation.text),
      evaluation.evaluation.text);
bar.update(evaluation.evaluation);
check('eval bar accepts a live engine payload', bar.element.querySelector('.evalbar-number').textContent === evaluation.evaluation.text);

// ---- session + step bar + streak ---------------------------------------
await api.resetSession();
const started = await api.startSession(['review_last_game', 'cards']);
check('startSession selects a subset', started.current === 'review_last_game');
const { createStepBar } = await import(`${REPO}/js/stepbar.js`);
const barHost = document.createElement('nav');
document.body.append(barHost);
createStepBar(barHost).render(started);
check('step bar renders all four steps', barHost.querySelectorAll('.step').length === 4,
      `${barHost.querySelectorAll('.step').length} rendered`);
check('step bar marks the current step', barHost.querySelector('.step.current')?.textContent.includes('Review last game'));
check('step bar dims unselected steps', barHost.querySelectorAll('.step.disabled').length === 2);

const done = await api.completeStep('review_last_game');
check('completing a step advances', done.session.current === 'cards');
check('completing a step moves the streak', done.streak.current === 1);

const { createStreakView } = await import(`${REPO}/js/streak_view.js`);
const streakHost = document.createElement('div');
createStreakView(streakHost).render(done.streak);
check('streak view renders', streakHost.textContent.includes('Current'), streakHost.textContent.trim());

// ---- start screen -------------------------------------------------------
const { renderStartScreen } = await import(`${REPO}/js/start_screen.js`);
const screenHost = document.createElement('div');
await api.resetSession();
renderStartScreen(screenHost, { session: await api.getSession(), onStarted: () => {} });
const boxes = screenHost.querySelectorAll('input[type=checkbox]');
check('start screen has four checkboxes', boxes.length === 4);
check('all checkboxes start checked', [...boxes].every((b) => b.checked));
const startBtn = screenHost.querySelector('button.primary');
check('Start button is enabled', startBtn && !startBtn.disabled);
boxes.forEach((b) => { b.checked = false; b.dispatchEvent(new dom.window.Event('change')); });
check('Start is disabled with nothing selected', startBtn.disabled);


// ---- animate.js: auto-replay ------------------------------------------
const { createReplay, createPause, sleep, replayDelayFor } = await import(`${REPO}/js/animate.js`);
const replayBoard = createBoard();
document.body.append(replayBoard.element);
await replayBoard.setFen(replayBoard.START_FEN);
const replayed = [];
const replay = createReplay({
  board: replayBoard,
  ucis: ['e2e4', 'e7e5', 'g1f3'],
  delayMs: 5,
  onMove: (r) => replayed.push(r.san),
});
check('replay completes', (await replay.promise) === true);
check('replay played every move in order', replayed.join(' ') === 'e4 e5 Nf3', replayed.join(' '));
check('replay left the board at the end of the line', replayBoard.getFen().includes('5N2'));

const cancelBoard = createBoard();
await cancelBoard.setFen(cancelBoard.START_FEN);
const cancelled = createReplay({ board: cancelBoard, ucis: ['e2e4', 'e7e5', 'g1f3'], delayMs: 40 });
cancelled.cancel();
check('a cancelled replay reports cancellation', (await cancelled.promise) === false);
check('cancel() is observable', cancelled.isCancelled === true);

check('replay delay is gentle for a short line', replayDelayFor(2) > 200, `${replayDelayFor(2)}ms`);
check('replay delay shrinks for a long line', replayDelayFor(40) < 150, `${replayDelayFor(40)}ms`);
check('replay delay never goes below the floor', replayDelayFor(1000) >= 90, `${replayDelayFor(1000)}ms`);

const pause = createPause(10);
check('an uninterrupted pause resolves true', (await pause.promise) === true);
replayBoard.destroy();
cancelBoard.destroy();

// ---- pgn_paste.js -----------------------------------------------------
const { createPgnPaste } = await import(`${REPO}/js/pgn_paste.js`);
let submitted = null;
const paste = createPgnPaste({ onSubmit: async (pgn) => { submitted = pgn; } });
document.body.append(paste.element);
check('paste widget starts collapsed', paste.element.open === false);
const pasteButton = paste.element.querySelector('button');
const pasteArea = paste.element.querySelector('textarea');

pasteButton.click();
await sleep(10);
check('submitting an empty box shows an error', paste.element.querySelector('.paste-error').textContent.length > 0);
check('an empty submit does not call onSubmit', submitted === null);

pasteArea.value = '[White "a"]\n[Black "b"]\n\n1. e4 e5 *\n';
pasteButton.click();
await sleep(20);
check('a filled box calls onSubmit', submitted !== null && submitted.includes('1. e4'));
check('the error clears on a valid submit', paste.element.querySelector('.paste-error').textContent === '');
paste.focus();
check('focus() opens the widget', paste.element.open === true);

// ---- review_view.js: the real review flow ----------------------------
// A game where White loses immediately, so a low-depth review finds a target.
const BLUNDER_PGN = '[White "test-player"]\n[Black "rival"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n';
await api.resetSession();
await api.startSession(null);
const pastedGame = (await api.pastePgn(BLUNDER_PGN)).game;
check('a pasted game reports its own move count', pastedGame.move_count === 4, `${pastedGame.move_count}`);
await api.startReview('review_last_game', { gameId: pastedGame.id, restart: true });

const { renderReviewView } = await import(`${REPO}/js/review_view.js`);
const reviewHost = document.createElement('main');
document.body.append(reviewHost);
const reviewStep = { step: 'review_last_game', position: 1, title: 'Review last game' };
let completedSession = null;
// The play step hands a game over through the store; mimic that here so the
// view reviews the pasted game rather than the most recently *played* one.
stateModule.set({ pendingGameId: pastedGame.id });
const reviewView = renderReviewView(reviewHost, {
  step: reviewStep,
  onCompleted: (session) => { completedSession = session; },
});

// Wait for the view to finish analysing and auto-replaying.
let reviewState = null;
for (let i = 0; i < 120; i++) {
  await sleep(250);
  reviewState = await api.reviewState('review_last_game');
  if (reviewState.status === 'ready') break;
}
check('review reaches ready', reviewState?.status === 'ready', reviewState?.status);
check('review found a target', reviewState && !reviewState.no_inaccuracy,
      JSON.stringify(reviewState?.no_inaccuracy));

// Wait for the auto-replay to finish and the eval bar to be populated.
let evalText = '—';
for (let i = 0; i < 40; i++) {
  await sleep(200);
  evalText = reviewHost.querySelector('.evalbar-number')?.textContent ?? '—';
  if (evalText !== '—' && evalText !== '…') break;
}
check('review view rendered a board', realPieces(reviewHost).length > 0, `${realPieces(reviewHost).length} pieces`);
check('review view rendered an eval bar', reviewHost.querySelector('.evalbar-number') !== null);
check('review view shows the eval number', /[0-9M]/.test(evalText), evalText);
check('review view offers Show answer', [...reviewHost.querySelectorAll('button')].some((b) => b.textContent === 'Show answer'));
check('review view offers Flip board', [...reviewHost.querySelectorAll('button')].some((b) => b.textContent === 'Flip board'));
check('review view reviews the game it was given', reviewHost.textContent.includes('rival'),
      reviewHost.textContent.includes('test-opponent') ? 'reviewed the wrong game' : 'opponent missing');
check('review view shows the move count of that game', reviewHost.textContent.includes('Moves4') || reviewHost.textContent.includes('Moves 4'));
check('review view offers a PGN paste fallback', reviewHost.querySelector('.pgn-paste') !== null);

// Solve it through the API the way the board would, then confirm the summary renders.
const targetFen = reviewState.target.fen_before;
const best = (await api.evaluate(targetFen)).best_move;
const wrongMove = 'h2h3';
const wrong = await api.reviewAttempt('review_last_game', wrongMove.slice(0, 2), wrongMove.slice(2, 4), null);
check('a wrong attempt is rejected with its own eval', wrong.correct === false && !!wrong.evaluation.text, wrong.evaluation.text);
const solved = await api.reviewAttempt('review_last_game', best.slice(0, 2), best.slice(2, 4), best.length > 4 ? best[4] : null);
check('the engine move solves the review', solved.correct === true);
check('solving returns a summary', solved.review.summary?.found_an_inaccuracy === true);
check('the summary names my move and the best move',
      !!solved.review.summary.my_move_san && !!solved.review.summary.best_move_san,
      `${solved.review.summary.my_move_san} vs ${solved.review.summary.best_move_san}`);
check('solving completes the step', solved.session?.steps.find((s) => s.step === 'review_last_game')?.completed === true);
check('solving advances to the play step', solved.session?.current === 'play');
reviewView.destroy();

// ---- play_view.js -----------------------------------------------------
const { renderPlayView } = await import(`${REPO}/js/play_view.js`);
const playHost = document.createElement('main');
document.body.append(playHost);
window.open = () => null; // jsdom does not implement window.open
const playView = renderPlayView(playHost, {
  step: { step: 'play', position: 2, title: 'Play a game' },
  onCompleted: () => {},
});
await sleep(1500); // the baseline call reaches chess.com
const playButtons = [...playHost.querySelectorAll('button')].map((b) => b.textContent);
check('play view offers an Open chess.com button', playButtons.some((t) => t.includes('Open chess.com')));
check('play view offers a fetch button', playButtons.some((t) => t.includes('fetch my game')));
check('play view offers a PGN paste fallback', playHost.querySelector('.pgn-paste') !== null);
check('play view reports the baseline game', /latest game so far|Could not reach/.test(playHost.textContent));
playView.destroy();

// ---- router wires the real views to their steps ----------------------
const routerModule = await import(`${REPO}/js/router.js`);
check('router module exposes createRouter', typeof routerModule.createRouter === 'function');

console.log(`\n${failures === 0 ? 'ALL FRONTEND CHECKS PASSED' : failures + ' FRONTEND CHECK(S) FAILED'}`);
process.exit(failures === 0 ? 0 : 1);
