/**
 * The revision-card drill (internally "inaccuracy cards"), in a real browser.
 *
 * Step 1 of the session: slips you picked from your own games, drilled again.
 * Covers what it says with nothing to drill (no cards yet, and all caught up);
 * making a card from a PGN and a move number; one card driven by real clicks
 * (the prompt, stepping back through the moves, a hint, a wrong try, the
 * right move, the result and the whole game); and deleting a card.
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
  console.log('\nBefore any card has been made');
  await open(page, base, 'empty');
  await waitForText(page, 'No revision cards yet.');
  const text = await page.innerText('.side-panel');
  check('it points to step 1 for making cards', text.includes('Make one in step 1'));
  check('there is no card-making button here', (await page.locator('button:text-is("Make a card"), button:text-is("New card")').count()) === 0);
  check('the step is current on the bar', (await page.innerText('.step.current')).includes('Revision cards'));
  await page.click('button:text-is("Continue to Opening cards")');
  await waitFor(page, 'the opening cards', () => document.querySelector('.step.current')?.textContent.includes('Opening cards'));
  check('Continue moves on to Opening cards', (await page.innerText('.step.current')).includes('Opening cards'));
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
  check('no Lichess link while solving', (await page.locator('a.lichess-link').count()) === 0);
  check('the move I played is, with what kind of slip it was', prompt.includes('You played 2.Nf3 here — a mistake.'));
  check('and drawn as a red arrow', (await board(page)).highlights.join() === 'red:g1f3', (await board(page)).highlights.join());
  let state = await board(page);
  check('the board shows the position', state.fen === POSITION);
  check('from my side', state.orientation === 'white');
  check('with the move that led there highlighted', JSON.stringify(state.lastMove) === '["e7","e5"]', JSON.stringify(state.lastMove));

  check('the moves before the slip are listed', (await page.innerText('.move-list')).replace(/\s+/g, ' ').includes('1. e4 e5'));
  await page.keyboard.press('ArrowLeft');
  await waitFor(page, 'one move back', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, AFTER_E4);
  state = await board(page);
  check('← steps back a move', state.fen === AFTER_E4);
  check('and the board takes no move there', state.movable !== 'white', String(state.movable));
  check('the red arrow is only on the slip position', state.highlights.length === 0, state.highlights.join());
  await page.keyboard.press('End');
  await waitFor(page, 'the slip position again', (fen) => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.getFen() === fen && b.ground.state.movable.color === 'white';
  }, POSITION);
  check('End comes back to the position, with the arrow', (await board(page)).highlights.join() === 'red:g1f3');

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
  await waitFor(page, 'the answer on the board', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, ANSWERED);
  state = await board(page);
  check('the board shows the answer played', state.fen === ANSWERED);
  check('the solving marks are gone', state.highlights.length === 0);
  const lichess = page.locator('a.lichess-link');
  check('Analyse at Lichess appears once answered', (await lichess.count()) === 1 && (await lichess.innerText()).includes('Analyse at Lichess'));
  check('it opens the game at the card position, my side down', (await lichess.getAttribute('href')).endsWith('?color=white#2'));
  check('in a new tab', (await lichess.getAttribute('target')) === '_blank');
  check('the whole game is listed now', (await page.innerText('.move-list')).includes('Bb5'));
  await page.keyboard.press('ArrowLeft');
  await waitFor(page, 'the slip position with arrows', (fen) => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.getFen() === fen && b.ground.state.drawable.shapes.length > 0;
  }, POSITION);
  state = await board(page);
  check('← from the answer: the slip, answer in green and game move in red', state.shapes.join() === 'green:f1c4,red:g1f3', state.shapes.join());
  check('the step counts once a card is answered', await page.evaluate(() =>
    window.chessTrainer.state().session?.steps.find((s) => s.step === 'inaccuracy_cards')?.completed === true));

  await page.click('button:text-is("Next card")');
  await waitForText(page, 'All caught up');
  check('Next card ends on the caught-up message', (await page.innerText('.side-panel')).includes('All caught up — no revision cards due.'));
}

// -- making a card ----------------------------------------------------------------

const PGN = '[White "test-player"]\n[Black "test-opponent"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *';

async function testMakeCard(page, base) {
  console.log('\nMaking a card (step 1)');
  await page.request.post(`${base}/__scenario`, { data: { step: 'make_card', inaccuracy: 'empty' } });
  await page.goto(base, { waitUntil: 'load' });
  await waitForText(page, 'type the number of the move you got wrong');
  check('it is the first step', (await page.innerText('.step.current')).includes('Make a revision card'));
  check('three steps on the bar', (await page.locator('.step').count()) === 3);

  await page.fill('textarea[aria-label="PGN"]', PGN);
  await page.fill('input[aria-label="Move number"]', '9');
  await page.click('button:text-is("Show position")');
  await waitForText(page, 'White has no move 9 in this game');
  check('a move the game lacks is explained', true);
  check('nothing to save yet', !(await page.isVisible('button:text-is("Save card")')));

  await page.fill('input[aria-label="Move number"]', '2');
  await page.keyboard.press('Enter');
  await waitForText(page, 'You played 2.Nf3 here.');
  await waitFor(page, 'the slip position', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, POSITION);
  const state = await board(page);
  check('the board shows the position before the move', state.fen === POSITION);
  check('with the move I played as a red arrow', state.highlights.join() === 'red:g1f3', state.highlights.join());
  check('and the moves before it listed', (await page.innerText('.move-list')).replace(/\s+/g, ' ').includes('1. e4 e5'));
  await page.keyboard.press('Home');
  await waitFor(page, 'the start', () => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen().startsWith('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP'));
  check('Home goes to the start of the game', (await board(page)).highlights.length === 0);
  await page.keyboard.press('End');
  await waitFor(page, 'the slip position', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, POSITION);

  await page.click('button:text-is("Save card")');
  await waitForText(page, 'Card saved for 2.Nf3 — first due 2026-11-03.');
  check('saving says when it is due', true);
  check('the answer is never shown', !(await page.innerText('body')).includes('Bc4'));
  check('the first card completes the step', await page.evaluate(() =>
    window.chessTrainer.state().session?.steps.find((s) => s.step === 'make_card')?.completed === true));
  check('the form stays, for another card', await page.isVisible('textarea[aria-label="PGN"]'));

  await page.click('button:text-is("Continue to Revision cards")');
  await waitFor(page, 'the revision cards', () => document.querySelector('.step.current')?.textContent.includes('Revision cards'));
  check('Continue goes on to Revision cards', (await page.innerText('.step.current')).includes('Revision cards'));
}

// -- deleting --------------------------------------------------------------------

async function testDelete(page, base) {
  console.log('\nDeleting a card');
  await open(page, base, 'one');
  await waitForText(page, 'Find the engine');
  check('Delete card is offered while solving', await page.isVisible('button:text-is("Delete card")'));

  await page.click('button:text-is("Delete card")');
  await waitForText(page, 'Delete this card?');
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
  check('Delete serves the next card (here: none left)', panel.includes('All caught up — no revision cards due.'));
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
  ['make a card', testMakeCard],
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
