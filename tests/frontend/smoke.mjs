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
const started = await api.startSession(['inaccuracy_cards']);
check('startSession selects a subset', started.current === 'inaccuracy_cards');
const { createStepBar } = await import(`${REPO}/js/stepbar.js`);
const barHost = document.createElement('nav');
document.body.append(barHost);
createStepBar(barHost).render(started);
check('step bar renders every step', barHost.querySelectorAll('.step').length === 3,
      `${barHost.querySelectorAll('.step').length} rendered`);
check('step bar marks the current step', barHost.querySelector('.step.current')?.textContent.includes('Revision cards'));
check('step bar dims unselected steps', barHost.querySelectorAll('.step.disabled').length === 2);

const done = await api.completeStep('inaccuracy_cards');
check('completing the only selected step finishes the session', done.session.current === null && done.session.finished);
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
const stepButtons = [...screenHost.querySelectorAll('button.step-button')];
check('start screen has one button per step', stepButtons.length === 3);
check('start screen asks nothing to tick', screenHost.querySelectorAll('input[type=checkbox]').length === 0);
let startedWith = null;
renderStartScreen(screenHost, { session: await api.getSession(), onStarted: (s) => { startedWith = s; } });
screenHost.querySelector('button.step-button[data-step="cards"]').click();
for (let i = 0; i < 50 && !startedWith; i++) await new Promise((r) => setTimeout(r, 20));
check('clicking a step starts the session there', startedWith?.current === 'cards', JSON.stringify(startedWith?.current));
check('every step stays available', startedWith?.steps.every((s) => s.enabled));
await api.resetSession();


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

// ---- revision cards: made from a PGN and a move number ------------------
// A game where White loses at once, so the real engine disagrees with 2.g4.
// Named after whoever the live server is configured for, so the game is "mine".
const me = (await api.getHealth()).chesscom_username || 'test-player';
const BLUNDER_PGN = `[White "${me}"]\n[Black "rival"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n`;
await api.resetSession();
await api.startSession(null, { startAt: 'inaccuracy_cards' });
const previewed = await api.previewInaccuracyCard({ pgn: BLUNDER_PGN, move_number: 2, colour: 'white' });
check('a card preview finds my move 2', previewed.move_label === '2.g4' && previewed.moves.length === 2,
      `${previewed.move_label} after ${previewed.moves.length} moves`);
let missing = null;
try { await api.previewInaccuracyCard({ pgn: BLUNDER_PGN, move_number: 9, colour: 'white' }); } catch (error) { missing = error.message; }
check('a move the game lacks is refused readably', /no move 9/.test(missing ?? ''), missing ?? 'accepted');
const made = await api.createInaccuracyCard({ pgn: BLUNDER_PGN, move_number: 2, colour: 'white' });
check('making the card schedules it', !!made.due_on && made.counts.total >= 1, JSON.stringify(made));
const bestHere = (await api.evaluate(previewed.fen)).best_move;
check('making the card does not give the answer away', !JSON.stringify(made).includes(bestHere));
const deckAfter = await api.nextInaccuracyCard();
check('the new card is not due until tomorrow', deckAfter.exhausted === true && deckAfter.counts.total >= 1,
      JSON.stringify(deckAfter.counts));

const { renderInaccuracyCardsView } = await import(`${REPO}/js/inaccuracy_cards_view.js`);
const revisionHost = document.createElement('main');
document.body.append(revisionHost);
const revisionView = renderInaccuracyCardsView(revisionHost, {
  step: { step: 'inaccuracy_cards', position: 1, title: 'Revision cards' },
  onCompleted: () => {},
});
for (let i = 0; i < 50 && !revisionHost.textContent.includes('All caught up'); i++) await sleep(50);
check('the revision view says nothing is due yet', revisionHost.textContent.includes('All caught up'));
check('and does not offer to make a card itself', ![...revisionHost.querySelectorAll('button')].some((b) => /Make a card|New card/.test(b.textContent)));
revisionView.destroy();

const { renderMakeCardView } = await import(`${REPO}/js/make_card_view.js`);
const makeHost = document.createElement('main');
document.body.append(makeHost);
const makeView = renderMakeCardView(makeHost, {
  step: { step: 'make_card', position: 2, title: 'Make a revision card' },
  onCompleted: () => {},
});
check('the make-card view asks for a PGN and a move number',
      makeHost.querySelector('textarea') !== null && makeHost.querySelector('input[type=number]') !== null);
check('the make-card view renders a board', realPieces(makeHost).length > 0, `${realPieces(makeHost).length} pieces`);
makeView.destroy();
await api.resetSession();

// ---- router wires the real views to their steps ----------------------
const routerModule = await import(`${REPO}/js/router.js`);
check('router module exposes createRouter', typeof routerModule.createRouter === 'function');



// ---- arrows.js --------------------------------------------------------
const arrows = await import(`${REPO}/js/arrows.js`);
const given = arrows.givenMove('e2e4');
check('arrows build a shape from a uci', given.length === 1 && given[0].orig === 'e2' && given[0].dest === 'e4');
check('the given arrow and the answer arrow differ',
      arrows.givenMove('e2e4')[0].brush !== arrows.answerMove('e2e4')[0].brush);
check('a malformed uci yields no shape', arrows.shapes(arrows.move('xx')).length === 0);

// ---- stats_table.js ---------------------------------------------------
const { renderStatsTable } = await import(`${REPO}/js/stats_table.js`);
const tableNode = renderStatsTable({
  total_games: 1000,
  mode: 'frequency',
  tie_note: 'two moves are played equally often; Stockfish picked between them.',
  engine_note: null,
  rows: [
    { san: 'c5', uci: 'c7c5', games: 600, share: 60, white: 200, draws: 300, black: 100,
      white_percent: 33.3, draw_percent: 50, black_percent: 16.7, average_rating: 2401,
      is_answer: true, is_engine_move: false, is_most_played: true, is_tied: true },
    { san: 'e5', uci: 'e7e5', games: 400, share: 40, white: 150, draws: 150, black: 100,
      white_percent: 37.5, draw_percent: 37.5, black_percent: 25, average_rating: 2410,
      is_answer: false, is_engine_move: true, is_most_played: false, is_tied: true },
  ],
});
check('stats table renders a row per move', tableNode.querySelectorAll('tbody tr').length === 2);
check('stats table highlights the answer', tableNode.querySelectorAll('tr.stats-answer').length === 1);
check('stats table shows the move, share and games',
      /c5/.test(tableNode.textContent) && /60\.0%/.test(tableNode.textContent) && /600/.test(tableNode.textContent));
check('stats table shows the average rating', /2401/.test(tableNode.textContent));
check('stats table draws a W/D/L bar', tableNode.querySelectorAll('.wdl-bar').length === 2);
check('stats table badges the answer', tableNode.querySelector('.badge-answer') !== null);
check('stats table badges a tie', tableNode.querySelector('.badge-tied') !== null);
check("stats table badges the engine's move on a frequency card",
      tableNode.querySelector('.badge-engine') !== null);
check('the most played move is not badged when it is the answer',
      tableNode.querySelector('.badge-played') === null);

// Engine mode: the answer is the engine's move, so the most played move is a
// different row and has to say so.
const engineModeTable = renderStatsTable({
  total_games: 11,
  mode: 'engine',
  tie_note: null,
  engine_note: 'Only 11 master games here, so Stockfish decides rather than frequency.',
  rows: [
    { san: 'a6', uci: 'a7a6', games: 7, share: 63.6, white: 3, draws: 2, black: 2,
      white_percent: 43, draw_percent: 29, black_percent: 28, average_rating: 2380,
      is_answer: false, is_engine_move: false, is_most_played: true, is_tied: false },
    { san: 'Nf6', uci: 'g8f6', games: 4, share: 36.4, white: 1, draws: 2, black: 1,
      white_percent: 25, draw_percent: 50, black_percent: 25, average_rating: 2390,
      is_answer: true, is_engine_move: true, is_most_played: false, is_tied: false },
  ],
});
check('stats table badges the most played move when it is not the answer',
      engineModeTable.querySelector('.badge-played') !== null);
check('the most played badge sits on the most played row',
      engineModeTable.querySelectorAll('tbody tr')[0].textContent.includes('most played'));
check('stats table shows the tie note', /equally often/.test(tableNode.textContent));
const emptyTable = renderStatsTable({ total_games: 0, mode: null, rows: [] });
check('an empty stats table says so', /No master moves/.test(emptyTable.textContent));

// ---- cards_view.js: the real drill ------------------------------------
const { renderCardsView } = await import(`${REPO}/js/cards_view.js`);
await api.resetSession();
await api.startSession(null);
// The step bar would have navigated here; without that the session's current
// step is still step 1 and "stays current" means nothing.
await api.jumpToStep('cards');

const cardsHost = document.createElement('main');
document.body.append(cardsHost);
const cardsView = renderCardsView(cardsHost, {
  step: { step: 'cards', position: 4, title: 'Opening cards' },
  onCompleted: () => {},
});

// Wait for the VIEW to reach its arrow phase before reading the server's
// state: the server keeps the last card in memory, so polling the API first
// can hand back a stale card from an earlier run.
for (let i = 0; i < 80; i++) {
  await sleep(250);
  if (/the arrow shows it/.test(cardsHost.textContent)) break;
}
check('cards view reaches the arrow phase', /the arrow shows it/.test(cardsHost.textContent),
      cardsHost.textContent.slice(0, 100));
const cardState = await api.cardState();
check('a card is served', cardState?.card != null, JSON.stringify(cardState?.counts));
const served = cardState.card;
check('the card has a given move', !!served.given_move_san, served.given_move_san);
check('the card names the side to find', ['white', 'black'].includes(served.side_to_move));
check('the card carries an opening name', !!served.opening_label, served.opening_label);
check('the card does not leak the answer', !JSON.stringify(served).toLowerCase().includes('answer'));
// Resolved by a real Stockfish search before the card was shown.
check('a frequency card says whether the engine agrees',
      served.mode !== 'frequency' || typeof served.engine_agrees === 'boolean',
      `${served.mode}: ${served.engine_agrees}`);
check('an engine-mode card has no agreement to report',
      served.mode !== 'engine' || served.engine_agrees === null,
      `${served.mode}: ${served.engine_agrees}`);

check('cards view renders a board', realPieces(cardsHost).length > 0, `${realPieces(cardsHost).length} pieces`);
check('cards view renders an eval bar', cardsHost.querySelector('.evalbar-number') !== null);
check('cards view shows the queue counts', /Due/.test(cardsHost.textContent) && /New/.test(cardsHost.textContent));
check('cards view asks for the arrow move',
      new RegExp(`Play ${served.given_move_san.replace(/[+#]/g, '\\$&')} `).test(cardsHost.textContent),
      `expected "Play ${served.given_move_san}" in the prompt`);
check('cards view offers Flip board', [...cardsHost.querySelectorAll('button')].some((b) => b.textContent === 'Flip board'));
check('the opening name is withheld until the given move is played',
      !cardsHost.textContent.includes(served.opening_label));

// White stays at the bottom by default, per the spec.
const cgOrientation = cardsHost.querySelector('.cg-wrap')?.classList.contains('orientation-black');
check('white is at the bottom by default', cgOrientation !== true);

// Answer through the API the way the board would, then confirm the result panel.
const wrongReply = served.side_to_move === 'black' ? ['a7', 'a6'] : ['a2', 'a3'];
const wrongCard = await api.cardAttempt(wrongReply[0], wrongReply[1], null);
check('a wrong card move is rejected with its own eval',
      wrongCard.correct === false && !!wrongCard.evaluation.text, wrongCard.evaluation.text);
check('a wrong card move does not finish the card', wrongCard.finished === false);
check('a wrong card move reveals no stats', wrongCard.stats == null);

const revealed = await api.showCardAnswer();
check('show answer reveals the move', !!revealed.answer_san, revealed.answer_san);
check('show answer grades as a failure', revealed.grade.quality === 1 && revealed.grade.passed === false);
check('show answer requeues the card', revealed.grade.requeued === true);
check('show answer returns the stats table', revealed.stats.rows.length > 0, `${revealed.stats.rows.length} rows`);
check('the stats table marks the answer', revealed.stats.rows.some((r) => r.is_answer));
check('the stats table marks the most played move', revealed.stats.rows.some((r) => r.is_most_played));
check("the stats table marks Stockfish's move", revealed.stats.rows.some((r) => r.is_engine_move));
check('show answer creates no branches', revealed.branches_created === 0);
check('show answer links the line to Lichess', /^https:\/\/lichess\.org\/analysis\/pgn\/.+\?color=white#\d+$/.test(revealed.lichess_url ?? ''), revealed.lichess_url);
check('the card step is marked and the streak moves',
      revealed.session != null && revealed.streak?.current >= 1);
check('the cards step stays current', revealed.session.current === 'cards');

cardsView.destroy();

// ---- router -----------------------------------------------------------
check('router exposes createRouter', typeof routerModule.createRouter === 'function');

console.log(`\n${failures === 0 ? 'ALL FRONTEND CHECKS PASSED' : failures + ' FRONTEND CHECK(S) FAILED'}`);
process.exit(failures === 0 ? 0 : 1);
