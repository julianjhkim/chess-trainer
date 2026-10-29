/**
 * Vendors chessground into frontend/vendor/chessground.
 *
 * The app must work offline with no CDN, so chessground is bundled once here
 * and the result is committed. Run `npm install && npm run vendor` to refresh
 * it after changing the pinned version in package.json.
 *
 * All piece and board graphics in chessground's stylesheets are inline data
 * URIs, so the three CSS files plus the JS bundle are fully self-contained.
 */

import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const destination = join(repoRoot, 'frontend', 'vendor', 'chessground');

// chessground's `exports` map does not expose ./package.json, so resolve the
// entry point and walk up to the package root instead of requiring it directly.
const entryPoint = require.resolve('chessground');
const packageRoot = dirname(dirname(entryPoint));
const { version, license } = JSON.parse(
  await readFile(join(packageRoot, 'package.json'), 'utf8'),
);

const STYLESHEETS = [
  'chessground.base.css',
  'chessground.brown.css',
  'chessground.cburnett.css',
];

await mkdir(destination, { recursive: true });

const result = await build({
  entryPoints: [entryPoint],
  outfile: join(destination, 'chessground.js'),
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  metafile: true,
});

for (const sheet of STYLESHEETS) {
  await copyFile(join(packageRoot, 'assets', sheet), join(destination, sheet));
}

try {
  await copyFile(join(packageRoot, 'LICENSE'), join(destination, 'LICENSE'));
} catch {
  console.warn('  (no LICENSE file in the chessground package)');
}

await writeFile(join(destination, 'VERSION'), `${version} ${license}\n`);

const bytes = Object.values(result.metafile.outputs)[0].bytes;
console.log(`Vendored chessground ${version} (${license})`);
console.log(`  bundle: ${(bytes / 1024).toFixed(1)} kB`);
console.log(`  styles: ${STYLESHEETS.join(', ')}`);
console.log(`  into:   frontend/vendor/chessground/`);
