/**
 * The inaccuracy-card drill, in a real browser.
 *
 * Step 1 of the session: positions where your reviewed games first went
 * wrong, drilled again. Covers what it says with nothing to drill (before any
 * review, and when all caught up) and one card driven by real clicks: the
 * prompt, a hint, a wrong try, the right move and the result; and deleting a
 * card, which asks first.
 *
 *     npm install && npx playwright install chromium
 *     npm run inaccuracy
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
const AFTER_E4 = fixture.moves[`${START}|e2e4`].fen;
const POSITION = fixture.moves[`${AFTER_E4}|e7e5`].fen;
const ANSWERED = fixture.moves[`${POSITION}|f1c4`].fen;

let failures = 0;
const check = (name, condition, extra = '') => {
  console.log(`${condition ? '  PASS' : '  FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
  if (!condition) failures++;
};

const board = (page) =>
  page.evaluate(() => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b
      ? {
          fen: b.getFen(),
          orientation: b.ground.state.orientation,
          lastMove: b.ground.state.lastMove ?? null,
          movable: b.ground.state.movable.color ?? null,
          shapes: b.ground.state.drawable.shapes.map((s) => `${s.brush}:${s.orig}${s.dest ?? ''}`).sort(),
          highlights: b.ground.state.drawable.autoShapes.map((s) => `${s.brush}:${s.orig}${s.dest ?? ''}`),
        }
      : null;
  });

async function waitFor(page, label, predicate, arg) {
  try {
    await page.waitForFunction(predicate, arg, { timeout: 15000 });
  } catch {
    throw new Error(`waiting for ${label}: ${JSON.stringify(await board(page))}`);
  }
}

const waitForText = (page, text) =>
  waitFor(page, `"${text}"`, (needle) => document.body.innerText.includes(needle), text);

async function clickSquare(page, square) {
  const { x, y } = await page.evaluate((key) => {
    const wrap = document.querySelector('.cg-wrap');
    const rect = wrap.querySelector('cg-board').getBoundingClientRect();
    const asWhite = !wrap.classList.contains('orientation-black');
    const file = key.charCodeAt(0) - 97;
    const rank = key.charCodeAt(1) - 49;
    return {
      x: rect.left + (((asWhite ? file : 7 - file) + 0.5) * rect.width) / 8,
      y: rect.top + (((asWhite ? 7 - rank : rank) + 0.5) * rect.height) / 8,
    };
  }, square);
  await page.mouse.click(x, y);
}

async function open(page, base, inaccuracy) {
  await page.request.post(`${base}/__scenario`, { data: { step: 'inaccuracy_cards', inaccuracy } });
  await page.goto(base, { waitUntil: 'load' });
}

// -- nothing to drill ---------------------------------------------------------

async function testEmptyDeck(page, base) {
  console.log('\nBefore any review has made a card');
  await open(page, base, 'empty');
  await waitForText(page, 'No inaccuracy cards yet.');
  const text = await page.innerText('.side-panel');
  check('it says how cards are made', text.includes('the first slip in each reviewed game becomes a card'));
  check('the step is first on the bar', (await page.innerText('.step.current')).includes('Inaccuracy cards'));
  await page.click('button:text-is("Continue to Play a game")');
  await waitFor(page, 'the play step', () => document.querySelector('.step.current')?.textContent.includes('Play a game'));
  check('Continue moves on to Play a game', (await page.innerText('.step.current')).includes('Play a game'));
}

async function testCaughtUp(page, base) {
  console.log('\nWith cards, but none due');
  await open(page, base, 'caught-up');
  await waitForText(page, 'All caught up');
  check('it says when the next card is due', (await page.innerText('.side-panel')).includes('The next one is due 2026-11-03.'));
}

// -- one card ------------------------------------------------------------------

async function testOneCard(page, base) {
  console.log('\nOne due card');
  await open(page, base, 'one');
  await waitForText(page, 'Find the engine');
  await waitFor(page, 'the board to accept a move', () => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.ground.state.movable.color === 'white';
  });

  const prompt = await page.innerText('.side-panel');
  check('the prompt names the game and the move', prompt.includes('From your game vs a-very-long-opponent-username') && prompt.includes('move 2, White to play'));
  check('the answer is not on screen', !prompt.includes('Bc4'));
  check('the move I played is, with what kind of slip it was', prompt.includes('You played 2.Nf3 here — a mistake.'));
  check('and drawn as a red arrow', (await board(page)).highlights.join() === 'red:g1f3', (await board(page)).highlights.join());
  let state = await board(page);
  check('the board shows the position', state.fen === POSITION);
  check('from my side', state.orientation === 'white');
  check('with the move that led there highlighted', JSON.stringify(state.lastMove) === '["e7","e5"]', JSON.stringify(state.lastMove));

  await page.click('button:text-is("Hint")');
  await waitForText(page, 'Hint: Move your bishop on f1.');
  check('Hint circles the piece', (await board(page)).highlights.join() === 'red:g1f3,yellow:f1');

  await clickSquare(page, 'g1');
  await clickSquare(page, 'f3');
  await waitForText(page, 'Nf3 is not it');
  await waitFor(page, 'the position to come back', (fen) => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.getFen() === fen && b.ground.state.movable.color === 'white';
  }, POSITION);
  check('a wrong try goes into the attempts', (await page.innerText('.attempt-list')).includes('Nf3'));
  check('the marks survive a wrong try', (await board(page)).highlights.join() === 'red:g1f3,yellow:f1');

  await clickSquare(page, 'f1');
  await clickSquare(page, 'c4');
  await waitForText(page, 'Correct — Bc4, after 2 tries.');
  const result = await page.innerText('.side-panel');
  check('the result recalls the game move', result.includes('2.Nf3 (a mistake, −21.4%)'));
  check('and the grade', result.includes('right with a hint (q=3)'));
  check('and the next due date', result.includes('2026-11-06 (6 days)'));
  state = await board(page);
  check('the board shows the answer played', state.fen === ANSWERED);
  check('answer in green, game move in red', state.shapes.join() === 'green:f1c4,red:g1f3', state.shapes.join());
  check('the solving marks are gone', state.highlights.length === 0);
  check('the step counts once a card is answered', await page.evaluate(() =>
    window.chessTrainer.state().session?.steps.find((s) => s.step === 'inaccuracy_cards')?.completed === true));

  await page.click('button:text-is("Next card")');
  await waitForText(page, 'All caught up');
  check('Next card ends on the caught-up message', (await page.innerText('.side-panel')).includes('All caught up — no inaccuracy cards due.'));
}

// -- deleting --------------------------------------------------------------------

async function testDelete(page, base) {
  console.log('\nDeleting a card');
  await open(page, base, 'one');
  await waitForText(page, 'Find the engine');
  check('Delete card is offered while solving', await page.isVisible('button:text-is("Delete card")'));

  await page.click('button:text-is("Delete card")');
  await waitForText(page, 'Delete this card for good?');
  check('it asks before deleting', await page.isVisible('button:text-is("Keep")'));
  check('the solving buttons step aside meanwhile', !(await page.isVisible('button:text-is("Hint")')));

  await page.click('button:text-is("Keep")');
  await waitFor(page, 'the solving buttons', () =>
    [...document.querySelectorAll('button')].some((b) => b.textContent === 'Hint'));
  check('Keep goes back to the card', (await page.innerText('.side-panel')).includes('You played 2.Nf3 here'));

  await page.click('button:text-is("Delete card")');
  await page.click('button:text-is("Delete")');
  await waitForText(page, 'All caught up');
  const panel = await page.innerText('.side-panel');
  check('Delete serves the next card (here: none left)', panel.includes('All caught up — no inaccuracy cards due.'));
  check('the deck shrinks', /In the deck\s*2/.test(panel), panel.split('\n').slice(0, 6).join(' | '));
  check('deleting does not count the step', await page.evaluate(() =>
    window.chessTrainer.state().session?.steps.find((s) => s.step === 'inaccuracy_cards')?.completed !== true));
}

// -- run ------------------------------------------------------------------------

const stub = await startStubServer();
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: VIEWPORT })).newPage();

page.on('pageerror', (error) => check('no page error', false, error.message));
page.on('console', (message) => {
  // The play step this test steps into asks for routes the stub lacks.
  if (message.type() === 'error' && !message.text().includes('Failed to load resource')) {
    check('no console error', false, message.text());
  }
});

for (const [name, run] of [
  ['empty deck', testEmptyDeck],
  ['caught up', testCaughtUp],
  ['one card', testOneCard],
  ['delete', testDelete],
]) {
  try {
    await run(page, stub.url);
  } catch (error) {
    check(`${name}: the case ran through`, false, error.message.split('\n')[0]);
  }
}

await browser.close();
await stub.close();
console.log(`\n${failures === 0 ? 'ALL INACCURACY CARD CHECKS PASSED' : failures + ' INACCURACY CARD CHECK(S) FAILED'}`);
process.exit(failures === 0 ? 0 : 1);
