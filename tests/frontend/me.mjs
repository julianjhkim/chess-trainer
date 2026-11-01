/**
 * The names I play under, edited from the top bar, in a real browser.
 *
 * The button at the right of the top bar lists them; clicking it opens an
 * editor to add and remove names, saved straight away.
 *
 *     npm install && npx playwright install chromium
 *     npm run me
 *
 * No server, engine, database or network: `stub_server.mjs` serves the real
 * frontend with canned API payloads.
 */

import { chromium } from 'playwright';

import { startStubServer } from './stub_server.mjs';

let failures = 0;
const check = (name, condition, extra = '') => {
  console.log(`${condition ? '  PASS' : '  FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
  if (!condition) failures++;
};

const stub = await startStubServer();
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
page.on('pageerror', (error) => check('no page error', false, error.message));

try {
  await page.request.post(`${stub.url}/__scenario`, { data: { step: 'make_card', names: ['test-player'] } });
  await page.goto(stub.url, { waitUntil: 'load' });
  const toggle = page.locator('.me-button');
  await page.waitForFunction(() => document.querySelector('.me-button')?.textContent.includes('test-player'));

  console.log('\nThe names button');
  const box = await toggle.boundingBox();
  const streak = await page.locator('#streak').boundingBox();
  check('it sits right of the streak', box.x > streak.x + streak.width, `${box.x} vs ${streak.x + streak.width}`);
  check('it shows my name', (await toggle.innerText()).includes('test-player'));
  check('the editor starts closed', !(await page.isVisible('.me-panel')));

  console.log('\nAdding and removing');
  await toggle.click();
  check('clicking opens the editor', await page.isVisible('.me-panel'));
  await page.fill('input[aria-label="New name"]', 'second-account');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('.me-button')?.textContent.includes('second-account'));
  check('a new name is added and shown', (await toggle.innerText()).includes('test-player, second-account'));
  check('the editor stays open for another', await page.isVisible('.me-panel'));

  await page.fill('input[aria-label="New name"]', 'SECOND-ACCOUNT');
  await page.click('.me-add button');
  await page.waitForTimeout(200);
  check('a repeat is not added twice', (await page.locator('.me-list li').count()) === 2);

  await page.click('button[aria-label="Remove test-player"]');
  await page.waitForFunction(() => !document.querySelector('.me-button')?.textContent.includes('test-player'));
  check('removing a name drops it', (await toggle.innerText()).trim() === '👤 second-account');

  const saved = await (await page.request.get(`${stub.url}/api/me`)).json();
  check('changes are saved straight away', JSON.stringify(saved.usernames) === '["second-account"]', JSON.stringify(saved));

  await page.keyboard.press('Escape');
  check('Escape closes the editor', !(await page.isVisible('.me-panel')));
  await toggle.click();
  await page.mouse.click(400, 600);
  check('clicking elsewhere closes it', !(await page.isVisible('.me-panel')));

  console.log('\nWith no names');
  await page.request.put(`${stub.url}/api/me`, { data: { usernames: [] } });
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => document.querySelector('.me-button')?.textContent.includes('Add your name'));
  check('the button invites adding one', (await toggle.innerText()).includes('Add your name'));
} catch (error) {
  check('the test ran through', false, error.message.split('\n')[0]);
}

await browser.close();
await stub.close();
console.log(`\n${failures === 0 ? 'ALL NAME CHECKS PASSED' : failures + ' NAME CHECK(S) FAILED'}`);
process.exit(failures === 0 ? 0 : 1);
