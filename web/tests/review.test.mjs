import test from 'node:test';
import assert from 'node:assert/strict';
import { blank, diffParts, nextOpenIndex, timecode } from '../src/review.ts';

test('diff preserves the exact original and proposed words including untrusted HTML', () => {
  const original = 'A <script>factory</script> is here.';
  const proposed = 'A needle is here.';
  assert.equal(diffParts(original, proposed, 'original').map(p => p.value).join(''), original);
  assert.equal(diffParts(original, proposed, 'proposed').map(p => p.value).join(''), proposed);
  assert.ok(diffParts(original, proposed, 'original').some(p => p.removed));
  assert.ok(diffParts(original, proposed, 'proposed').some(p => p.added));
});
test('invisible-only corrections are not usable', () => {
  for (const value of ['', '  \n\t', '\u200b\u2060\ufeff']) assert.equal(blank(value), true);
  assert.equal(blank('We need a factory.'), false);
});
test('timestamps are useful seek targets', () => {
  assert.equal(timecode(125.9), '2:05');
  assert.equal(timecode(0), '0:00');
});
test('timecode shows hours from 3600 s and survives bad input', () => {
  assert.equal(timecode(3600), '1:00:00');
  assert.equal(timecode(4500), '1:15:00');
  assert.equal(timecode(3599.9), '59:59');
  assert.equal(timecode(59.9), '0:59');
  assert.equal(timecode(-5), '0:00');
  assert.equal(timecode(NaN), '0:00');
  assert.equal(timecode(Infinity), '0:00');
});
test('nextOpenIndex moves to the next unstaged row and stays put at the end', () => {
  const ids = ['a', 'b', 'c', 'd'];
  const staged = (set) => (id) => set.has(id);
  assert.equal(nextOpenIndex(ids, staged(new Set(['a'])), 0), 1);
  assert.equal(nextOpenIndex(ids, staged(new Set(['a', 'b'])), 0), 2);
  assert.equal(nextOpenIndex(ids, staged(new Set(['a', 'c'])), 0), 1);
  assert.equal(nextOpenIndex(ids, staged(new Set(['c'])), 1), 3, 'skips a later staged row');
  assert.equal(nextOpenIndex(ids, staged(new Set(['c', 'd'])), 2), 2, 'nothing open after: stay');
  assert.equal(nextOpenIndex(ids, staged(new Set(['a'])), 3), 3, 'no wrap to an open row before');
  assert.equal(nextOpenIndex([], staged(new Set()), -1), -1);
});
