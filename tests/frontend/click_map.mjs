/**
 * Board click mapping, in a real browser.
 *
 * The jsdom smoke test cannot catch this class of bug: jsdom has no layout, so
 * every rectangle is zero and a board whose cached bounds have gone stale looks
 * fine. This drives the real app in Chromium with real mouse clicks at square
 * centres and asserts that the square chessground picks is the square clicked —
 * at each point where the layout around the board changes (the eval bar, the
 * opening name, the stats table, the attempts list).
 *
 *     npm install && npx playwright install chromium
 *     npm run clicks
 *
 * No server, engine, database or network: `stub_server.mjs` serves the real
 * frontend with canned API payloads.
 */

import { chromium } from 'playwright';

import { startStubServer } from './stub_server.mjs';

const VIEWPORT = { width: 1280, height: 900 };
/** A click must land on the square it was aimed at; 0 tolerance, by design. */
const MAX_DRIFT_PX = 0.75;

const WHITE_SQUARES = squares(['1', '2']);
const BLACK_SQUARES = squares(['7', '8']);

function squares(ranks) {
  const files = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  return ranks.flatMap((rank) => files.map((file) => file + rank));
}

let failures = 0;
/** Prefixed onto browser errors so a stray one is traceable to a stage. */
let stage = 'boot';

const check = (name, condition, extra = '') => {
  console.log(`${condition ? '  PASS' : '  FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
  if (!condition) failures++;
};

// -- page helpers ---------------------------------------------------------

/** The viewport coordinates of a square's centre, from the live board rect. */
function squareCentre(page, key) {
  return page.evaluate((square) => {
    const wrap = document.querySelector('.cg-wrap');
    const rect = wrap.querySelector('cg-board').getBoundingClientRect();
    const asWhite = !wrap.classList.contains('orientation-black');
    const file = square.charCodeAt(0) - 97;
    const rank = square.charCodeAt(1) - 49;
    const column = asWhite ? file : 7 - file;
    const row = asWhite ? 7 - rank : rank;
    return {
      x: rect.left + ((column + 0.5) * rect.width) / 8,
      y: rect.top + ((row + 0.5) * rect.height) / 8,
    };
  }, key);
}

/**
 * Chessground's own notion of the selected square.
 *
 * Read from its state rather than the DOM: the rendered `square.selected`
 * lands a frame later (the redraw is debounced through requestAnimationFrame),
 * which would race every click.
 */
const selectedSquare = (page) =>
  page.evaluate(
    () => [...window.chessTrainer.boards].at(-1).ground.state.selected ?? null,
  );

/**
 * How far chessground's cached bounds have drifted from the board's real
 * position. This is the quantity the bug is made of: every click, drag and
 * arrow is resolved against the cached rectangle.
 */
const boundsDrift = (page) =>
  page.evaluate(() => {
    const board = [...window.chessTrainer.boards].at(-1);
    const cached = board.ground.state.dom.bounds();
    const live = board.ground.state.dom.elements.board.getBoundingClientRect();
    return {
      dx: cached.left - live.left,
      dy: cached.top - live.top,
      dw: cached.width - live.width,
      dh: cached.height - live.height,
    };
  });

/** Click each square's centre and report the ones that selected elsewhere. */
async function checkClicks(page, label, keys) {
  stage = label;
  const wrong = [];
  for (const key of keys) {
    const { x, y } = await squareCentre(page, key);
    await page.mouse.click(x, y);
    const got = await selectedSquare(page);
    if (got !== key) wrong.push(`${key}→${got ?? 'nothing'}`);
  }
  check(
    `${label}: every square centre selects its own square`,
    wrong.length === 0,
    wrong.length ? `${wrong.length}/${keys.length} wrong: ${wrong.slice(0, 6).join(' ')}` : `${keys.length} squares`,
  );
}

/** Let any pending re-measure run: the board re-measures once per frame. */
const settle = (page) =>
  page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );

async function checkBounds(page, label) {
  stage = label;
  await settle(page);
  const drift = await boundsDrift(page);
  const worst = Math.max(...Object.values(drift).map(Math.abs));
  check(
    `${label}: chessground's cached bounds match the board`,
    worst <= MAX_DRIFT_PX,
    `off by dx=${drift.dx.toFixed(1)} dy=${drift.dy.toFixed(1)} dw=${drift.dw.toFixed(1)}`,
  );
}

const boardRect = (page) =>
  page.evaluate(() => {
    const { left, top, width } = document.querySelector('.cg-wrap').getBoundingClientRect();
    return { left, top, width };
  });

/**
 * The board should not move at all when content lands beside it — the cached
 * bounds are then never wrong in the first place, and the board does not jump
 * under the pointer. `checkBounds` covers the shifts that cannot be designed
 * away; this covers the ones that can.
 */
function checkStill(label, before, after) {
  check(
    `${label}: the board did not move`,
    Math.abs(before.left - after.left) < 0.5 &&
      Math.abs(before.top - after.top) < 0.5 &&
      Math.abs(before.width - after.width) < 0.5,
    `moved by ${(after.left - before.left).toFixed(1)},${(after.top - before.top).toFixed(1)}`,
  );
}

/** Play a move by clicking its two squares. */
async function clickMove(page, from, to) {
  for (const key of [from, to]) {
    const { x, y } = await squareCentre(page, key);
    await page.mouse.click(x, y);
  }
}

const waitForText = (page, text) =>
  page.waitForFunction((needle) => document.body.innerText.includes(needle), text, {
    timeout: 15000,
  });

const waitForInteractive = (page) =>
  page.waitForFunction(
    () => {
      const board = [...(window.chessTrainer?.boards ?? [])].at(-1);
      return !!board && board.ground.state.movable.color !== undefined;
    },
    undefined,
    { timeout: 15000 },
  );

// -- the views ------------------------------------------------------------

async function testCardsView(page, base) {
  console.log('\nOpening cards view');
  await page.request.post(`${base}/__scenario`, { data: { step: 'cards' } });
  await page.goto(base, { waitUntil: 'load' });

  // 1. The arrow phase: the queue and prompt panels have just been filled in.
  await waitForText(page, 'the arrow shows it');
  await waitForInteractive(page);
  await checkBounds(page, 'cards/arrow');
  await checkClicks(page, 'cards/arrow', WHITE_SQUARES);
  const placed = await boardRect(page);

  // 2. Play the arrow move; the opening name appears beside the board.
  await clickMove(page, 'e2', 'e4');
  await waitForText(page, 'No arrow this time');
  check(
    'cards: the opening name is shown once the given move is played',
    (await page.innerText('body')).includes("King's Pawn Game"),
  );
  await waitForInteractive(page);
  await checkBounds(page, 'cards/opening-name');
  checkStill('cards/opening-name', placed, await boardRect(page));
  await checkClicks(page, 'cards/opening-name', BLACK_SQUARES);

  // 3. Answer it: the stats table, the grade and the result headline appear.
  await clickMove(page, 'e7', 'e5');
  await page.waitForSelector('.stats-table', { timeout: 15000 });
  await checkBounds(page, 'cards/stats-table');
  checkStill('cards/stats-table', placed, await boardRect(page));

  // 4. The next card shrinks the panel back again.
  await page.getByRole('button', { name: 'Next card' }).click();
  await waitForText(page, 'the arrow shows it');
  await waitForInteractive(page);
  await checkBounds(page, 'cards/next-card');
  await checkClicks(page, 'cards/next-card', WHITE_SQUARES);
}

async function testReviewView(page, base) {
  console.log('\nGame review view');
  await page.request.post(`${base}/__scenario`, { data: { step: 'review_new_game' } });
  await page.goto(base, { waitUntil: 'load' });

  // 1. The target is ready: game card, prompt and PGN paste all just rendered.
  await waitForText(page, 'where your game first went wrong');
  await waitForInteractive(page);
  await checkBounds(page, 'review/target');
  await checkClicks(page, 'review/target', WHITE_SQUARES);
  const placed = await boardRect(page);

  // 2. A wrong attempt adds the attempts card, growing the panel.
  await clickMove(page, 'e2', 'e4');
  await page.waitForSelector('.attempt-list', { timeout: 15000 });
  await waitForInteractive(page);
  await checkBounds(page, 'review/attempts');
  checkStill('review/attempts', placed, await boardRect(page));
  await checkClicks(page, 'review/attempts', WHITE_SQUARES);
}

/**
 * A shift the stylesheet cannot design away.
 *
 * The CSS keeps the side panel a fixed width so its content cannot slide the
 * board, but fonts, the top bar rewrapping and a zoom change can all still
 * move it. This nudges the board sideways without changing its size at all,
 * which is the case chessground never notices on its own.
 */
async function testLayoutShift(page, base) {
  console.log('\nAfter the board is moved without being resized');
  await page.request.post(`${base}/__scenario`, { data: { step: 'cards' } });
  await page.goto(base, { waitUntil: 'load' });
  await waitForText(page, 'the arrow shows it');
  await waitForInteractive(page);

  const moved = await page.evaluate(async () => {
    const wrap = document.querySelector('.cg-wrap');
    const before = wrap.getBoundingClientRect();
    document.querySelector('.view').style.paddingLeft = '160px';
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const after = wrap.getBoundingClientRect();
    return { dx: after.left - before.left, dw: after.width - before.width };
  });
  check(
    'shifted: the board moved sideways without changing size',
    Math.abs(moved.dx) > 20 && Math.abs(moved.dw) < 0.5,
    `dx=${moved.dx.toFixed(1)} dw=${moved.dw.toFixed(1)}`,
  );
  await checkBounds(page, 'shifted');
  await checkClicks(page, 'shifted', WHITE_SQUARES);
}

async function testWindowResize(page, base) {
  console.log('\nAfter a window resize');
  await page.request.post(`${base}/__scenario`, { data: { step: 'cards' } });
  await page.goto(base, { waitUntil: 'load' });
  await waitForText(page, 'the arrow shows it');
  await waitForInteractive(page);

  await page.setViewportSize({ width: 1024, height: 820 });
  await page.waitForTimeout(250);
  await checkBounds(page, 'cards/resized');
  await checkClicks(page, 'cards/resized', WHITE_SQUARES);

  await page.setViewportSize(VIEWPORT);
  await page.waitForTimeout(250);
  await checkBounds(page, 'cards/resized-back');
  await checkClicks(page, 'cards/resized-back', WHITE_SQUARES);
}

// -- run ------------------------------------------------------------------

const stub = await startStubServer();
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: VIEWPORT });
const page = await context.newPage();

// The board's arrows are measured from the same cached rectangle as its
// clicks: drawn at a stale size they come out NaN and the SVG complains, so
// the browser's own errors are part of what this test watches.
page.on('pageerror', (error) => check(`${stage}: no page error`, false, error.message));
page.on('console', (message) => {
  if (message.type() === 'error') check(`${stage}: no console error`, false, message.text());
});

for (const [name, run] of [
  ['opening cards', testCardsView],
  ['game review', testReviewView],
  ['layout shift', testLayoutShift],
  ['window resize', testWindowResize],
]) {
  try {
    await run(page, stub.url);
  } catch (error) {
    check(`${name}: the view ran through`, false, error.message.split('\n')[0]);
  }
}

await browser.close();
await stub.close();

console.log(
  `\n${failures === 0 ? 'ALL BOARD CLICK CHECKS PASSED' : failures + ' BOARD CLICK CHECK(S) FAILED'}`,
);
process.exit(failures === 0 ? 0 : 1);
