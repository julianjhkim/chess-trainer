/**
 * Stepping through a reviewed game with the arrow keys, in a real browser.
 *
 * The review drills one position, but the moves around it are what make it
 * make sense, so ← / → walk the game: the moves leading to the position while
 * the drill is open, and the whole game once it is over, with the engine's
 * answer sitting beside the move actually played. This drives that with real
 * key presses and mouse clicks and reads the board chessground is showing.
 *
 * It also covers the Hint button (a circle on the piece to move), the "Why"
 * card that follows the review, and a duplicate-link bug: the game card used
 * to gain one more "Open on chess.com" link on every progress poll.
 *
 *     npm install && npx playwright install chromium
 *     npm run review
 *
 * No server, engine, database or network: `stub_server.mjs` serves the real
 * frontend with canned API payloads.
 */

import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

import { startStubServer } from './stub_server.mjs';

const VIEWPORT = { width: 1280, height: 900 };

const HERE = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(await readFile(join(HERE, 'fixtures', 'board.json'), 'utf8'));

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
/** The position after each ply of 1.e4 e5 2.Nf3 Nc6 3.Bb5, index 0 = start. */
const LINE = ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1b5'];
const FENS = [START];
for (const uci of LINE) FENS.push(fixture.moves[`${FENS.at(-1)}|${uci}`].fen);
const ANSWER_FEN = fixture.moves[`${FENS[2]}|f1c4`].fen;

let failures = 0;
const check = (name, condition, extra = '') => {
  console.log(`${condition ? '  PASS' : '  FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
  if (!condition) failures++;
};

/** What the board and move list are showing right now. */
const snapshot = (page) =>
  page.evaluate(() => {
    const board = [...(window.chessTrainer?.boards ?? [])].at(-1);
    const moves = [...document.querySelectorAll('.move-list .move:not(.move-placeholder)')];
    return {
      fen: board?.getFen() ?? null,
      movable: board?.ground.state.movable.color ?? null,
      shapes: (board?.ground.state.drawable.autoShapes ?? [])
        .concat(board?.ground.state.drawable.shapes ?? [])
        .map((s) => `${s.brush}:${s.orig}${s.dest ?? ''}`)
        .sort(),
      moves: moves.map((m) => m.textContent),
      current: moves.findIndex((m) => m.classList.contains('move-current')),
      inaccuracy: moves.findIndex((m) => m.classList.contains('move-inaccuracy')),
      links: [...document.querySelectorAll('.side-panel a')].filter((a) =>
        a.textContent.includes('Open on chess.com'),
      ).length,
    };
  });

async function waitFor(page, label, predicate, arg) {
  try {
    await page.waitForFunction(predicate, arg, { timeout: 15000 });
  } catch {
    throw new Error(`waiting for ${label}: ${JSON.stringify(await snapshot(page))}`);
  }
}

/** Wait until the board shows `fen` (each step waits on the server). */
const waitForFen = (page, fen, label) =>
  waitFor(
    page,
    label,
    (expected) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === expected,
    fen,
  );

const waitForText = (page, text) =>
  waitFor(page, `"${text}"`, (needle) => document.body.innerText.includes(needle), text);

async function clickSquare(page, square) {
  const { x, y } = await page.evaluate((key) => {
    const wrap = document.querySelector('.cg-wrap');
    const rect = wrap.querySelector('cg-board').getBoundingClientRect();
    const asWhite = !wrap.classList.contains('orientation-black');
    const file = key.charCodeAt(0) - 97;
    const rank = key.charCodeAt(1) - 49;
    const column = asWhite ? file : 7 - file;
    const row = asWhite ? 7 - rank : rank;
    return {
      x: rect.left + ((column + 0.5) * rect.width) / 8,
      y: rect.top + ((row + 0.5) * rect.height) / 8,
    };
  }, square);
  await page.mouse.click(x, y);
}

async function press(page, key, fen, label) {
  await page.keyboard.press(key);
  await waitForFen(page, fen, label);
  // The draw that lands the FEN then sets arrows and interactivity; let it.
  await page.waitForTimeout(60);
  return snapshot(page);
}

// -- the drill ------------------------------------------------------------

async function testWhileDrilling(page, base) {
  console.log('\nWhile the drill is open');
  await page.request.post(`${base}/__scenario`, {
    data: { step: 'review_last_game', review: 'browse' },
  });
  await page.goto(base, { waitUntil: 'load' });
  await waitForText(page, 'where your game first went wrong');
  await waitFor(page, 'the live position', () => {
    const board = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return board && board.ground.state.movable.color !== undefined;
  });

  let state = await snapshot(page);
  check('the game card has exactly one chess.com link after several polls', state.links === 1, `${state.links} links`);
  check('the list holds only the moves before the slip', JSON.stringify(state.moves) === '["e4","e5"]', JSON.stringify(state.moves));
  check('the last of them is current', state.current === 1, String(state.current));
  check('the board is on the position to solve', state.fen === FENS[2]);

  state = await press(page, 'ArrowLeft', FENS[1], '← to after 1.e4');
  check('← steps back one move', state.fen === FENS[1]);
  check('the board takes no move away from the live position', state.movable === null, String(state.movable));
  check('the list follows', state.current === 0, String(state.current));

  state = await press(page, 'Home', START, 'Home to the start');
  check('Home goes to the start', state.fen === START);
  check('nothing is current at the start', state.current === -1, String(state.current));

  await page.keyboard.press('ArrowLeft');
  await page.waitForTimeout(150);
  check('← at the start stays there', (await snapshot(page)).fen === START);

  state = await press(page, 'ArrowRight', FENS[1], '→ to after 1.e4');
  check('→ steps forward', state.fen === FENS[1]);

  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await waitForFen(page, FENS[2], '→ → to the live position');
  await page.waitForTimeout(150);
  state = await snapshot(page);
  check('→ never goes past the position being drilled', state.fen === FENS[2]);
  check('back at the live position the board takes a move again', state.movable === 'white', String(state.movable));

  // Arrow keys typed into the PGN box move its caret, not the game.
  await page.evaluate(() => {
    document.querySelector('.pgn-paste').open = true;
    document.querySelector('.pgn-paste textarea').focus();
  });
  await page.keyboard.press('ArrowLeft');
  await page.waitForTimeout(150);
  check('arrows inside the PGN box leave the board alone', (await snapshot(page)).fen === FENS[2]);
  await page.evaluate(() => document.activeElement.blur());

  // Clicking a move in the list jumps there.
  await page.click('.move-list .move >> text=e4');
  await waitForFen(page, FENS[1], 'click on e4');
  check('clicking a move jumps to it', (await snapshot(page)).fen === FENS[1]);

  // A hint taken while browsing brings the board back to the live position.
  await page.click('button:text-is("Hint")');
  await waitForFen(page, FENS[2], 'the hint returning to the live position');
  await waitForText(page, 'Hint: Move your bishop on f1.');
  await page.waitForTimeout(100);
  state = await snapshot(page);
  check('Hint names the piece to move', (await page.innerText('.side-panel')).includes('Move your bishop on f1.'));
  check('Hint circles its square', state.shapes.join() === 'yellow:f1', state.shapes.join());
  check('the hint does not give the destination away', !(await page.innerText('.side-panel')).includes('c4'));

  state = await press(page, 'ArrowLeft', FENS[1], '← away from the hinted position');
  check('the circle stays with the live position', state.shapes.length === 0, state.shapes.join());
  state = await press(page, 'End', FENS[2], 'End back to the live position');
  check('and comes back with it', state.shapes.join() === 'yellow:f1', state.shapes.join());
}

// -- after solving --------------------------------------------------------

async function testAfterSolving(page) {
  console.log('\nOnce the review is over');
  await waitFor(page, 'the board to accept a move', () => {
    const board = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return board && board.ground.state.movable.color === 'white';
  });
  await clickSquare(page, 'f1');
  await clickSquare(page, 'c4');
  await waitForText(page, 'Review complete');
  check('the summary says a hint was used', (await page.innerText('.side-panel')).includes('with a hint'));
  await waitForFen(page, ANSWER_FEN, 'the answer position');
  await page.waitForTimeout(100);

  let state = await snapshot(page);
  check('the list now holds the whole game', state.moves.length === LINE.length, JSON.stringify(state.moves));
  check('the slip is marked', state.inaccuracy === 2, String(state.inaccuracy));
  check('the answer is shown with a green arrow', state.shapes.join() === 'green:f1c4', state.shapes.join());
  check('no game move is current while the answer is shown', state.current === -1, String(state.current));

  state = await press(page, 'ArrowLeft', FENS[2], '← from the answer');
  check('← from the answer goes to the position before the slip', state.fen === FENS[2]);
  check('there, both moves are drawn', state.shapes.join() === 'green:f1c4,red:g1f3', state.shapes.join());
  check('the board stays read-only', state.movable === null, String(state.movable));

  state = await press(page, 'ArrowRight', FENS[3], '→ to the move played');
  check('→ goes on to the move actually played', state.fen === FENS[3]);
  check('which is current in the list', state.current === 2, String(state.current));

  state = await press(page, 'End', FENS[5], 'End of the game');
  check('End reaches the last move of the game', state.fen === FENS[5]);
  check('arrows are gone away from the slip', state.shapes.length === 0, state.shapes.join());

  state = await press(page, 'ArrowLeft', FENS[4], '← from the end');
  check('← works back through the game', state.fen === FENS[4]);

  state = await press(page, 'Home', START, 'Home');
  check('Home goes to the start of the game', state.fen === START);

  await page.click('.nav-row button[aria-label^="Next"]');
  await waitForFen(page, FENS[1], 'the ▶ button');
  check('the ▶ button steps too', (await snapshot(page)).fen === FENS[1]);

  // -- why
  await waitForText(page, 'You played: 2.Nf3');
  const why = await page.innerText('.explanation');
  check('Why shows the best line', why.includes('Best: 2.Bc4'), JSON.stringify(why.slice(0, 80)));
  check('Why reads back the punishing reply', why.includes('The engine answers 2...Nc6.'));

  await page.click('.explain-mine .explain-move >> text=Nc6');
  await waitForFen(page, FENS[4], 'a move from my line');
  state = await snapshot(page);
  check('clicking a move in a line shows that position', state.fen === FENS[4]);
  check('a line position carries no answer arrow', state.shapes.length === 0, state.shapes.join());

  state = await press(page, 'ArrowLeft', FENS[2], '← from a line position');
  check('← from a line position goes back to where it branched', state.fen === FENS[2]);

  await page.click('.explain-best .explain-move');
  await waitForFen(page, ANSWER_FEN, 'the best line');
  check('the best line is clickable too', (await snapshot(page)).fen === ANSWER_FEN);
}

// -- run ------------------------------------------------------------------

const stub = await startStubServer();
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: VIEWPORT });
const page = await context.newPage();

page.on('pageerror', (error) => check('no page error', false, error.message));
page.on('console', (message) => {
  if (message.type() === 'error') check('no console error', false, message.text());
});

try {
  await testWhileDrilling(page, stub.url);
  await testAfterSolving(page);
} catch (error) {
  check('the review ran through', false, error.message.split('\n')[0]);
}

await browser.close();
await stub.close();

console.log(
  `\n${failures === 0 ? 'ALL REVIEW NAVIGATION CHECKS PASSED' : failures + ' REVIEW NAVIGATION CHECK(S) FAILED'}`,
);
process.exit(failures === 0 ? 0 : 1);
