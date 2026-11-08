/**
 * The revision-card drill (internally "inaccuracy cards"), in a real browser.
 *
 * Step 1 of the session: slips you picked from your own games, drilled again
 * (made in step 2).
 * Covers what it says with nothing to drill (no cards yet, and all caught up);
 * finding puzzles in a pasted game; one card driven by real clicks
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
const REPLIED = fixture.moves[`${ANSWERED}|b8c6`].fen;
const SOLVED = fixture.moves[`${REPLIED}|g1f3`].fen;
const AFTER_NF3 = fixture.moves[`${POSITION}|g1f3`].fen;
const PUNISHED = fixture.moves[`${AFTER_NF3}|g8f6`].fen;

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
  await waitForText(page, 'No puzzles yet.');
  const text = await page.innerText('.side-panel');
  check('it points to step 2 for making puzzles', text.includes('Make some in step 2, “Make puzzles”'));
  check('there is no card-making button here', (await page.locator('button:text-is("Make a card"), button:text-is("New card")').count()) === 0);
  check('the step is current on the bar', (await page.innerText('.step.current')).includes('Puzzles'));
  check('no Continue button', (await page.locator('button:has-text("Continue")').count()) === 0);
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
  await waitForText(page, 'Find the best move');
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
  await waitForText(page, 'Correct — 2.Bc4, after 1 wrong move.');
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
  check('it sits right after Next puzzle', await page.evaluate(() => {
    const link = document.querySelector('a.lichess-link');
    return link?.previousElementSibling?.textContent === 'Next puzzle';
  }));
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

  await page.click('button:text-is("Next puzzle")');
  await waitForText(page, 'All caught up');
  check('Next puzzle ends on the caught-up message', (await page.innerText('.side-panel')).includes('All caught up — no puzzles due.'));
}

// -- a puzzle ---------------------------------------------------------------------

async function testPuzzle(page, base) {
  console.log('\nA card that is a puzzle');
  await open(page, base, 'puzzle');
  await waitFor(page, 'the board to accept a move', () => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.ground.state.movable.color === 'white';
  });
  check('the opponent’s last move has played in', (await board(page)).fen === POSITION);

  await clickSquare(page, 'f1');
  await clickSquare(page, 'c4');
  await waitFor(page, 'the reply and my turn again', (fen) => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.getFen() === fen && b.ground.state.movable.color === 'white';
  }, REPLIED);
  let state = await board(page);
  check('a right move brings the opponent’s reply', state.fen === REPLIED);
  check('with the reply highlighted', JSON.stringify(state.lastMove) === '["b8","c6"]', JSON.stringify(state.lastMove));
  check('my game move is no longer drawn', !state.highlights.includes('red:g1f3'), state.highlights.join());
  check('the moves join the move list', (await page.innerText('.move-list')).replace(/\s+/g, ' ').includes('Bc4 Nc6'));
  check('the prompt says how far it has gone', (await page.innerText('.side-panel')).includes('So far: 2.Bc4 Nc6 — your move.'));
  check('no result yet', (await page.locator('.result-headline').count()) === 0);

  await page.keyboard.press('ArrowLeft');
  await waitFor(page, 'a step back', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, ANSWERED);
  check('← steps back through the puzzle moves too', (await board(page)).movable !== 'white');
  await page.keyboard.press('End');
  await waitFor(page, 'the live position again', (fen) => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.getFen() === fen && b.ground.state.movable.color === 'white';
  }, REPLIED);

  await clickSquare(page, 'g1');
  await clickSquare(page, 'f3');
  await waitForText(page, 'Correct — 2.Bc4 Nc6 3.Nf3, no wrong moves.');
  await waitFor(page, 'the end of the line on the board', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, SOLVED);
  check('the board ends on the puzzle’s last move', (await board(page)).fen === SOLVED);
  for (const [key, fen] of [['ArrowLeft', REPLIED], ['ArrowLeft', ANSWERED], ['ArrowLeft', POSITION]]) {
    await page.keyboard.press(key);
    await waitFor(page, `back to ${fen}`, (f) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === f, fen);
  }
  check('← walks back along the line to the slip position', (await board(page)).fen === POSITION);
  await waitFor(page, 'the arrows at the slip', () =>
    [...(window.chessTrainer?.boards ?? [])].at(-1)?.ground.state.drawable.shapes.length === 2);
  check('where the answer and the game move are drawn', (await board(page)).shapes.join() === 'green:f1c4,red:g1f3', (await board(page)).shapes.join());
  await page.keyboard.press('ArrowRight');
  await waitFor(page, 'the game move', () => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && (b.ground.state.lastMove ?? []).join('') === 'g1f3';
  });
  state = await board(page);
  check('→ from the slip goes on to the move I played', JSON.stringify(state.lastMove) === '["g1","f3"]', JSON.stringify(state.lastMove));
}

// -- a punishment puzzle -----------------------------------------------------------

async function testPunish(page, base) {
  console.log('\nPunishing my own mistake');
  await open(page, base, 'punish');
  await waitFor(page, 'the board to accept a move', () => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.ground.state.movable.color === 'black';
  });
  let state = await board(page);
  check('it is played as my opponent', state.orientation === 'black');
  check('right after my mistake, which played in', state.fen === AFTER_NF3 && JSON.stringify(state.lastMove) === '["g1","f3"]');
  check('nothing is drawn: the game’s next move could be the answer', state.highlights.length === 0, state.highlights.join());
  const prompt = await page.innerText('.side-panel');
  check('the prompt names my mistake and the side to play', prompt.includes('You played 2.Nf3 — a mistake. Play Black: punish it, as your opponent should have.'));

  await clickSquare(page, 'g8');
  await clickSquare(page, 'f6');
  await waitForText(page, 'Correct — 2...Nf6, no wrong moves.');
  const result = await page.innerText('.side-panel');
  check('the result names my mistake', result.includes('Your mistake') && result.includes('2.Nf3 (a mistake, −21.4%)'));
  check('and how the game went on', result.includes('The game went on') && result.includes('2...Nc6'));
  await waitFor(page, 'the answer on the board', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, PUNISHED);
  await page.keyboard.press('ArrowLeft');
  await waitFor(page, 'the arrows', () => [...(window.chessTrainer?.boards ?? [])].at(-1)?.ground.state.drawable.shapes.length === 2);
  state = await board(page);
  check('← shows the answer in green and the game’s move in red', state.shapes.join() === 'green:g8f6,red:b8c6', state.shapes.join());
  check('Lichess opens it from Black’s side', (await page.locator('a.lichess-link').getAttribute('href')).includes('color=black'));
}

// -- making a card ----------------------------------------------------------------

const PGN = '[White "test-player"]\n[Black "test-opponent"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *';

async function testMakeCard(page, base) {
  console.log('\nMaking puzzles (step 2)');
  await page.request.post(`${base}/__scenario`, { data: { step: 'make_card', inaccuracy: 'empty' } });
  await page.goto(base, { waitUntil: 'load' });
  await waitForText(page, 'Stockfish checks every move, yours and your opponent');
  check('it is called Make puzzles', (await page.innerText('.step.current')).includes('Make puzzles'));
  check('three steps on the bar', (await page.locator('.step').count()) === 3);
  check('no move number to type', (await page.locator('input[type=number]').count()) === 0);

  await page.click('button:text-is("Find puzzles")');
  await waitForText(page, 'Paste a game first.');
  check('an empty paste is explained', true);

  await page.fill('textarea[aria-label="PGN"]', PGN);
  await page.click('button:text-is("Find puzzles")');
  await waitForText(page, 'Checking your moves…');
  check('the scan shows its progress', (await page.locator('.scan-progress progress').count()) === 1);
  check('and can be stopped', await page.isVisible('button:text-is("Stop")'));

  await waitForText(page, 'Found 1 puzzle in this game — saved.');
  const panel = await page.innerText('.side-panel');
  check('each puzzle names the mistake, the side to punish it and its length', panel.includes('2.Nf3, your mistake (−21.4%): punish it as Black, 2 moves'), panel.replace(/\s+/g, ' ').slice(0, 300));
  check('and when it is first due', panel.includes('first due 2026-11-03'));
  check('mistakes with no clear punishment are listed as not puzzles', panel.includes('Not puzzles (no single clear punishment): 2...Nc6.'));
  check('the answer is never shown', !(await page.innerText('body')).includes('Nf6'));
  await waitFor(page, 'the puzzle position', (fen) => {
    const b = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return b && b.getFen() === fen && (b.ground.state.lastMove ?? []).join('') === 'g1f3';
  }, AFTER_NF3);
  check('the board shows the position right after the mistake', (await board(page)).shapes.length === 0);
  await page.keyboard.press('End');
  await waitFor(page, 'the end of the game', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() !== fen, AFTER_NF3);
  check('← / → step through the whole game', (await page.innerText('.move-list')).includes('Bb5'));
  await page.click('button.found-puzzle');
  await waitFor(page, 'the puzzle position again', (fen) => [...(window.chessTrainer?.boards ?? [])].at(-1)?.getFen() === fen, AFTER_NF3);
  check('clicking a puzzle goes back to its position', true);
  check('saving puzzles completes the step', await page.evaluate(() =>
    window.chessTrainer.state().session?.steps.find((s) => s.step === 'make_card')?.completed === true));
  check('the form stays, for another game', await page.isVisible('textarea[aria-label="PGN"]'));
  check('no Continue button', (await page.locator('button:has-text("Continue")').count()) === 0);
}

// -- deleting --------------------------------------------------------------------

async function testDelete(page, base) {
  console.log('\nDeleting a card');
  await open(page, base, 'one');
  await waitForText(page, 'Find the best move');
  check('Delete puzzle is offered while solving', await page.isVisible('button:text-is("Delete puzzle")'));

  await page.click('button:text-is("Delete puzzle")');
  await waitForText(page, 'Delete this puzzle?');
  check('it asks before deleting', await page.isVisible('button:text-is("Keep")'));
  check('the solving buttons step aside meanwhile', !(await page.isVisible('button:text-is("Hint")')));

  await page.click('button:text-is("Keep")');
  await waitFor(page, 'the solving buttons', () =>
    [...document.querySelectorAll('button')].some((b) => b.textContent === 'Hint'));
  check('Keep goes back to the card', (await page.innerText('.side-panel')).includes('You played 2.Nf3 here'));

  await page.click('button:text-is("Delete puzzle")');
  await page.click('button:text-is("Delete")');
  await waitForText(page, 'All caught up');
  const panel = await page.innerText('.side-panel');
  check('Delete serves the next puzzle (here: none left)', panel.includes('All caught up — no puzzles due.'));
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
  ['puzzle', testPuzzle],
  ['punish', testPunish],
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
