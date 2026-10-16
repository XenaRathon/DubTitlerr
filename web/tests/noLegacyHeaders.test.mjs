import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const FORBIDDEN = [
  'X-Review-Token',
  'X-Review-Admin-Token',
  'dubtitlerr_review_token',
  'dubtitlerr_admin_token',
];

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

function offenders(dir) {
  return files(dir).flatMap((f) => {
    const text = readFileSync(f, 'utf8').toLowerCase();
    return FORBIDDEN.filter((word) => text.includes(word.toLowerCase())).map((word) => `${f}: ${word}`);
  });
}

test('the web sources never name a retired token header or storage key', () => {
  assert.deepEqual(offenders(new URL('../src', import.meta.url).pathname), []);
});

test('the built bundle never names one either (run through npm run test:bundle)', (t) => {
  const dist = new URL('../dist', import.meta.url).pathname;
  if (!existsSync(dist)) return t.skip('web/dist is not built; npm run test:bundle builds it first');
  assert.ok(
    files(dist).some((f) => f.endsWith('.js')),
    'the bundle has JavaScript to scan',
  );
  assert.deepEqual(offenders(dist), []);
});
