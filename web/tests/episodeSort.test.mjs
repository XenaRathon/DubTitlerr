import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EPISODE_SORTS,
  LINE_SORTS,
  readSortPref,
  sortEpisodes,
  writeSortPref,
} from '../src/lib/episodeSort.js';

const ep = (show, season, name, admitted) => ({ stem: `${show}/${season}/${name}`, show, season, name, admitted });
// The server order: most admitted first.
const served = [
  ep('Neon Harbor', 'Season 1', 'Neon Harbor S01E10', 5),
  ep('Alpha Show', 'Season 10', 'Alpha Show S10E01', 3),
  ep('Neon Harbor', 'Season 1', 'Neon Harbor S01E02', 3),
  ep('Alpha Show', 'Season 2', 'Alpha Show S02E01', 0),
];

test('default keeps the server order untouched', () => {
  assert.deepEqual(
    sortEpisodes(served, 'default').map((e) => e.name),
    served.map((e) => e.name),
  );
});

test('episode order sorts show, then season, then episode, numbers as numbers', () => {
  assert.deepEqual(
    sortEpisodes(served, 'episode').map((e) => e.name),
    ['Alpha Show S02E01', 'Alpha Show S10E01', 'Neon Harbor S01E02', 'Neon Harbor S01E10'],
  );
});

test('pending puts the most repairs to check first, ties in episode order', () => {
  assert.deepEqual(
    sortEpisodes(served, 'pending').map((e) => e.name),
    ['Neon Harbor S01E10', 'Alpha Show S10E01', 'Neon Harbor S01E02', 'Alpha Show S02E01'],
  );
});

test('sorting never mutates the input array', () => {
  const copy = served.slice();
  sortEpisodes(served, 'episode');
  assert.deepEqual(served, copy);
});

test('a stored preference is restored only when it is a known value', () => {
  const store = new Map([
    ['a', 'episode'],
    ['b', 'bogus'],
  ]);
  const storage = { getItem: (k) => store.get(k) ?? null };
  assert.equal(readSortPref(storage, 'a', EPISODE_SORTS, 'default'), 'episode');
  assert.equal(readSortPref(storage, 'b', EPISODE_SORTS, 'default'), 'default');
  assert.equal(readSortPref(storage, 'missing', LINE_SORTS, 'risk'), 'risk');
  // An inherited Object key is not a sort option.
  store.set('c', 'toString');
  assert.equal(readSortPref(storage, 'c', LINE_SORTS, 'risk'), 'risk');
});

test('unavailable storage falls back instead of throwing', () => {
  const broken = {
    getItem() {
      throw new Error('denied');
    },
    setItem() {
      throw new Error('denied');
    },
  };
  assert.equal(readSortPref(broken, 'a', LINE_SORTS, 'risk'), 'risk');
  assert.equal(readSortPref(undefined, 'a', LINE_SORTS, 'risk'), 'risk');
  assert.doesNotThrow(() => writeSortPref(broken, 'a', 'time'));
  assert.doesNotThrow(() => writeSortPref(undefined, 'a', 'time'));
});

test('writeSortPref stores the value under the key', () => {
  const store = new Map();
  writeSortPref({ setItem: (k, v) => store.set(k, v) }, 'k', 'time');
  assert.equal(store.get('k'), 'time');
});

test('oldest activity first sorts by oldest_pending_at, nulls last, ties in episode order', () => {
  const at = (name, when) => ({ ...ep('S', 'Season 1', name, 1), oldest_pending_at: when });
  const rows = [
    at('S E04', null),
    at('S E03', '2026-10-02T08:00:00Z'),
    at('S E02', '2026-09-30T23:59:59Z'),
    at('S E01', '2026-10-02T08:00:00Z'),
  ];
  assert.ok(EPISODE_SORTS.includes('oldest'));
  assert.deepEqual(
    sortEpisodes(rows, 'oldest').map((e) => e.name),
    ['S E02', 'S E01', 'S E03', 'S E04'],
  );
});
