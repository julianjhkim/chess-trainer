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

console.log(`\n${failures === 0 ? 'ALL FRONTEND CHECKS PASSED' : failures + ' FRONTEND CHECK(S) FAILED'}`);
process.exit(failures === 0 ? 0 : 1);
