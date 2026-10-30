/**
 * What an opening card says on its question screen, in a real browser.
 *
 * The card is drilled the way a person drills it — play the arrow move, then
 * answer — so the assertions are about what is actually on screen at each
 * point, not about what a render function returned. In particular: whether the
 * most played move is also Stockfish's, which has to be said *before* the
 * answer is known and must not give the answer away.
 *
 *     npm install && npx playwright install chromium
 *     npm run cards
 *
 * No server, engine, database or network: `stub_server.mjs` serves the real
 * frontend with canned API payloads.
 */

import { chromium } from 'playwright';

import { startStubServer } from './stub_server.mjs';

const VIEWPORT = { width: 1280, height: 900 };

const AGREES = "The most played move is also the engine's best move.";
const DISAGREES =
  "Heads-up: the most played move is NOT the engine's best move — find the most played one.";

let failures = 0;
const check = (name, condition, extra = '') => {
  console.log(`${condition ? '  PASS' : '  FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
  if (!condition) failures++;
};

/**
 * Wait for a condition, saying what was being waited for if it never comes.
 *
 * A bare "waitForFunction timed out" in a five-step drill says nothing about
 * which step stalled, so each wait carries a label and dumps what the card was
 * doing at the time.
 */
async function waitFor(page, label, predicate, arg) {
  try {
    await page.waitForFunction(predicate, arg, { timeout: 15000 });
  } catch {
    const state = await page.evaluate(() => {
      const board = [...(window.chessTrainer?.boards ?? [])].at(-1);
      return {
        status: document.querySelector('#status')?.textContent,
        selected: board?.ground.state.selected ?? null,
        movable: board?.ground.state.movable.color ?? null,
        fen: board?.getFen(),
        // A board whose cached rectangle has gone stale drops clicks
        // silently, which looks exactly like a card that never advanced.
        boundsLeft: board?.ground.state.dom.bounds().left,
        liveLeft: board?.ground.state.dom.elements.board.getBoundingClientRect().left,
        prompt: document
          .querySelector('.side-panel .card:nth-child(2)')
          ?.innerText.replace(/\s+/g, ' ')
          .slice(0, 120),
      };
    });
    throw new Error(`waiting for ${label}: ${JSON.stringify(state)}`);
  }
}

const waitForText = (page, text) =>
  waitFor(page, `"${text}"`, (needle) => document.body.innerText.includes(needle), text);

const prompt = (page) => page.innerText('.side-panel .card:nth-child(2)');

/**
 * Wait until the board will accept the move.
 *
 * The prompt says "play the arrow" before the arrow is drawn and the board
 * made movable, so the text alone is not enough to click on.
 */
const waitForInteractive = (page) =>
  waitFor(page, 'the board to accept a move', () => {
    const board = [...(window.chessTrainer?.boards ?? [])].at(-1);
    return !!board && board.ground.state.movable.color !== undefined;
  });

/** Click a square's centre, as a person would. */
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

/** Open a card and play its given move, landing on the question screen. */
async function openQuestion(page, base, engineAgrees) {
  await page.request.post(`${base}/__scenario`, {
    data: { step: 'cards', engineAgrees },
  });
  await page.goto(base, { waitUntil: 'load' });
  await waitForText(page, 'the arrow shows it');
  await waitForInteractive(page);
  await clickSquare(page, 'e2');
  await clickSquare(page, 'e4');
  await waitForText(page, 'No arrow this time');
}

// -- the question screen --------------------------------------------------

async function testAgreement(page, base) {
  console.log('\nWhen the engine agrees with the masters');
  await openQuestion(page, base, true);
  const text = await prompt(page);

  check('the agreement line is shown, word for word', text.includes(AGREES), quote(text));
  check('it does not warn as well', !text.includes('Heads-up'));
  check('the opening name is there too', text.includes("King's Pawn Game"));
  check(
    'the question still says the most played move is the answer',
    text.includes('the most played move is the answer'),
  );
}

async function testDisagreement(page, base) {
  console.log('\nWhen the engine disagrees');
  await openQuestion(page, base, false);
  const text = await prompt(page);

  check('the warning is shown, word for word', text.includes(DISAGREES), quote(text));
  check('it does not also claim agreement', !text.includes(AGREES));
  check(
    'the warning is marked as a warning, not a footnote',
    (await page.locator('.engine-disagrees').count()) === 1,
  );
}

async function testSilence(page, base) {
  console.log('\nWhen there is nothing to say');
  await openQuestion(page, base, null);
  const text = await prompt(page);

  check('neither line is shown', !text.includes(AGREES) && !text.includes('Heads-up'), quote(text));
  check('the rest of the question is unchanged', text.includes('No arrow this time'));
}

async function testTheAnswerIsNotGivenAway(page, base) {
  console.log('\nThe question gives nothing away');
  await openQuestion(page, base, false);
  const text = await prompt(page);

  // The answer is e5 and the engine's move is c5; neither may be named before
  // the card is answered.
  check('no move is named in the warning', !/\b(e5|c5)\b/.test(text), quote(text));
  check(
    'no stats table yet',
    (await page.locator('.stats-table').count()) === 0,
  );
}

// -- the table afterwards -------------------------------------------------

async function testTheTableMarksBothMoves(page, base) {
  console.log('\nAfter answering');
  await openQuestion(page, base, false);
  await clickSquare(page, 'e7');
  await clickSquare(page, 'e5');
  await page.waitForSelector('.stats-table', { timeout: 15000 });

  const marked = await page.evaluate(() =>
    [...document.querySelectorAll('.stats-table tbody tr')].map((tr) => ({
      san: tr.querySelector('td')?.firstChild?.textContent?.trim(),
      badges: [...tr.querySelectorAll('.badge')].map((b) => b.textContent),
    })),
  );
  const badgesOf = (san) => marked.find((r) => r.san === san)?.badges ?? [];

  check('the answer is badged', badgesOf('e5').includes('answer'), JSON.stringify(badgesOf('e5')));
  check(
    "the engine's move is badged",
    badgesOf('c5').includes('engine'),
    JSON.stringify(badgesOf('c5')),
  );
  check(
    'the most played move says so only when it is not the answer',
    !badgesOf('e5').includes('most played'),
    JSON.stringify(badgesOf('e5')),
  );
  check(
    'the question line is gone once the card is answered',
    !(await prompt(page)).includes('Heads-up'),
  );
}

const quote = (text) => JSON.stringify(text.replace(/\s+/g, ' ').slice(0, 120));

// -- run ------------------------------------------------------------------

const stub = await startStubServer();
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: VIEWPORT });
const page = await context.newPage();

page.on('pageerror', (error) => check('no page error', false, error.message));
page.on('console', (message) => {
  if (message.type() === 'error') check('no console error', false, message.text());
});

for (const [name, run] of [
  ['agreement', testAgreement],
  ['disagreement', testDisagreement],
  ['silence', testSilence],
  ['secrecy', testTheAnswerIsNotGivenAway],
  ['stats table', testTheTableMarksBothMoves],
]) {
  try {
    await run(page, stub.url);
  } catch (error) {
    check(`${name}: the case ran through`, false, error.message.split('\n')[0]);
  }
}

await browser.close();
await stub.close();

console.log(
  `\n${failures === 0 ? 'ALL CARD PROMPT CHECKS PASSED' : failures + ' CARD PROMPT CHECK(S) FAILED'}`,
);
process.exit(failures === 0 ? 0 : 1);
