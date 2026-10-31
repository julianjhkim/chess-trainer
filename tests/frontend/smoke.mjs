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
const stepButtons = [...screenHost.querySelectorAll('button.step-button')];
check('start screen has one button per step', stepButtons.length === 4);
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
// Named after whoever the live server is configured for, so the pasted game is "mine".
const me = (await api.getHealth()).chesscom_username || 'test-player';
const BLUNDER_PGN = `[White "${me}"]\n[Black "rival"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n`;
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
const hinted = await api.reviewHint('review_last_game');
check('a hint names the square the answer moves from', hinted.hint.square === best.slice(0, 2), JSON.stringify(hinted.hint));
check('the hint does not give the destination away', !JSON.stringify(hinted.hint).includes(best.slice(2, 4)) || best.slice(0, 2) === best.slice(2, 4));
let explainedEarly = null;
try { await api.reviewExplain('review_last_game'); } catch (error) { explainedEarly = error.message; }
check('no explanation before the position is solved', explainedEarly !== null, explainedEarly ?? 'it explained');
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
check('the summary notes the hint', solved.review.summary.used_hint === true);
const explained = await api.reviewExplain('review_last_game');
check('the explanation starts the best line with the answer', explained.best.moves[0]?.uci === best,
      explained.best.moves.map((m) => m.label).join(' '));
check('the explanation starts my line with my move', explained.mine.moves[0]?.uci === solved.review.summary.my_move_uci,
      explained.mine.moves.map((m) => m.label).join(' '));
check('the real engine gives a line longer than one move', explained.best.moves.length > 1 && explained.mine.moves.length > 1);
check('the explanation says something about each line', explained.best.notes.length > 0 && explained.mine.notes.length > 0,
      JSON.stringify(explained.mine.notes));
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
check('the card step is marked and the streak moves',
      revealed.session != null && revealed.streak?.current >= 1);
check('the cards step stays current', revealed.session.current === 'cards');

cardsView.destroy();

// ---- router covers all four steps -------------------------------------
check('router exposes createRouter', typeof routerModule.createRouter === 'function');

console.log(`\n${failures === 0 ? 'ALL FRONTEND CHECKS PASSED' : failures + ' FRONTEND CHECK(S) FAILED'}`);
process.exit(failures === 0 ? 0 : 1);
