import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_WARMING_RETRIES,
  buildQuery,
  createLatest,
  formatAge,
  pageWindow,
  stageClass,
  summarizeCounts,
  warmingRetryDelay,
} from '../src/lib/dashboard.js';

test('stageClass maps each pipeline stage to its status token', () => {
  assert.equal(stageClass('transcribed'), 'info');
  assert.equal(stageClass('repaired'), 'info');
  assert.equal(stageClass('muxed'), 'ok');
  assert.equal(stageClass('failed'), 'bad');
  assert.equal(stageClass('stale'), 'warn');
  assert.equal(stageClass('pending-review'), 'warn');
});

test('stageClass falls back to one token for unknown stages', () => {
  assert.equal(typeof stageClass('bogus'), 'string');
  assert.equal(stageClass('bogus'), stageClass(''));
});

test('formatAge renders seconds, minutes, hours, and unknown', () => {
  assert.equal(formatAge(14.2), '14 s');
  assert.equal(formatAge(0), '0 s');
  assert.equal(formatAge(59.9), '59 s');
  assert.equal(formatAge(180), '3 min');
  assert.equal(formatAge(7200), '2 h');
  assert.equal(formatAge(null), 'unknown');
  assert.equal(formatAge(undefined), 'unknown');
  assert.equal(formatAge(NaN), 'unknown');
});

test('summarizeCounts lists every stage in order, missing means zero', () => {
  assert.deepEqual(summarizeCounts({ counts_per_stage: { muxed: 120, failed: 1 } }), [
    { stage: 'transcribed', count: 0 },
    { stage: 'repaired', count: 0 },
    { stage: 'muxed', count: 120 },
    { stage: 'failed', count: 1 },
    { stage: 'stale', count: 0 },
    { stage: 'pending-review', count: 0 },
  ]);
  assert.deepEqual(summarizeCounts({}), [
    { stage: 'transcribed', count: 0 },
    { stage: 'repaired', count: 0 },
    { stage: 'muxed', count: 0 },
    { stage: 'failed', count: 0 },
    { stage: 'stale', count: 0 },
    { stage: 'pending-review', count: 0 },
  ]);
});

test('pageWindow shows at most five pages around the current one', () => {
  assert.deepEqual(pageWindow(1, 1), [1]);
  assert.deepEqual(pageWindow(1, 10), [1, 2, 3, 4, 5]);
  assert.deepEqual(pageWindow(5, 10), [3, 4, 5, 6, 7]);
  assert.deepEqual(pageWindow(9, 10), [6, 7, 8, 9, 10]);
  assert.deepEqual(pageWindow(2, 3), [1, 2, 3]);
});

test('buildQuery encodes the show filter with page and limit', () => {
  assert.equal(buildQuery({ show: '', page: 1, limit: 50 }), '?page=1&limit=50');
  assert.equal(buildQuery({ show: 'One Pace', page: 2, limit: 50 }), '?show=One%20Pace&page=2&limit=50');
  assert.equal(buildQuery({ show: '  ', page: 0, limit: 999 }), '?page=1&limit=200');
});

test('createLatest: only the most recently started request may apply its result', () => {
  const latest = createLatest();
  const first = latest.begin();
  const second = latest.begin();
  assert.equal(latest.isCurrent(first), false, 'the older response arrives late and must be dropped');
  assert.equal(latest.isCurrent(second), true);
});

test('createLatest: a response applies unless something newer has started, and cancel() drops everything', () => {
  const latest = createLatest();
  const only = latest.begin();
  assert.equal(latest.isCurrent(only), true);
  latest.cancel();
  assert.equal(latest.isCurrent(only), false, 'a page that was torn down applies nothing');
});

test('createLatest: stale responses never overwrite newer state (simulated out-of-order fetches)', async () => {
  const latest = createLatest();
  let shown = null;
  const fetchPage = (page, delay) => {
    const id = latest.begin();
    return new Promise((resolve) => setTimeout(resolve, delay)).then(() => {
      if (latest.isCurrent(id)) shown = page;
    });
  };
  await Promise.all([fetchPage(1, 30), fetchPage(2, 5)]);
  assert.equal(shown, 2, 'page 2 was asked for last, so its answer wins even though page 1 landed later');
});

test('warmingRetryDelay retries a bounded number of times then gives up', () => {
  assert.equal(MAX_WARMING_RETRIES, 5);
  for (let attempt = 0; attempt < MAX_WARMING_RETRIES; attempt++) {
    assert.equal(typeof warmingRetryDelay(attempt), 'number', `attempt ${attempt}`);
    assert.ok(warmingRetryDelay(attempt) > 0);
  }
  assert.equal(warmingRetryDelay(MAX_WARMING_RETRIES), null);
  assert.equal(warmingRetryDelay(99), null);
  assert.equal(warmingRetryDelay(-1), null, 'a garbage attempt number does not schedule a retry');
});
