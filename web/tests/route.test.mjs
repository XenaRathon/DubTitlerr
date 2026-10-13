import test from 'node:test';
import assert from 'node:assert/strict';
import { VIEWS, hashFor, parseHash } from '../src/lib/route.js';

test('every known hash resolves to its view', () => {
  for (const view of ['inbox', 'shared', 'dashboard', 'glossary', 'runs', 'settings']) {
    assert.equal(parseHash('#/' + view), view);
  }
});

test('empty, bare and unknown hashes fall back to the inbox', () => {
  for (const hash of [
    '',
    '#',
    '#/',
    '#/nope',
    '#nope',
    '#/Glossary',
    '#/glossary-x',
    '#/__proto__',
    '#/constructor',
    undefined,
    null,
  ]) {
    assert.equal(parseHash(hash), 'inbox', String(hash));
  }
});

test('a trailing slash, query or sub-path does not change the view', () => {
  assert.equal(parseHash('#/glossary/'), 'glossary');
  assert.equal(parseHash('#/glossary?show=One%20Pace'), 'glossary');
  assert.equal(parseHash('#/shared/anything'), 'shared');
});

test('a hash without the slash still names its view', () => {
  assert.equal(parseHash('#settings'), 'settings');
});

test('hashFor builds the canonical hash and round-trips through parseHash', () => {
  for (const view of VIEWS) {
    assert.equal(hashFor(view), '#/' + view);
    assert.equal(parseHash(hashFor(view)), view);
  }
});

test('hashFor normalizes an unknown view to the inbox hash', () => {
  assert.equal(hashFor('nope'), '#/inbox');
  assert.equal(hashFor(undefined), '#/inbox');
});

test('VIEWS lists the six views in sidebar order', () => {
  assert.deepEqual([...VIEWS], ['inbox', 'shared', 'dashboard', 'glossary', 'runs', 'settings']);
});

test('runs has its own hash and is not confused with a prefix match', () => {
  assert.equal(parseHash('#/runs'), 'runs');
  assert.equal(parseHash('#/runs/'), 'runs');
  assert.equal(parseHash('#/runs-queue'), 'inbox');
  assert.equal(parseHash('#/run'), 'inbox');
  assert.equal(hashFor('runs'), '#/runs');
});
