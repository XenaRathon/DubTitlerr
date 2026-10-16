import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildOp,
  describeError,
  filterTerms,
  isDirty,
  sortTerms,
  validateTerm,
} from '../src/lib/glossary.js';
import { ApiError } from '../src/lib/api.js';

test('filterTerms returns a copy of the whole list when the query is empty', () => {
  const list = ['Fixer', 'Needle'];
  const out = filterTerms(list, '');
  assert.deepEqual(out, list);
  assert.notEqual(out, list);
});

test('filterTerms matches case-insensitively on substrings', () => {
  assert.deepEqual(filterTerms(['Fixer Upper', 'Needle', 'fixation'], 'FIX'), ['Fixer Upper', 'fixation']);
  assert.deepEqual(filterTerms(['Fixer', 'Needle'], 'zzz'), []);
});

test('filterTerms matches hard_fixes entries on either side of the pair', () => {
  const entries = [
    ['asce', 'ace'],
    ['marimo', 'marimo'],
  ];
  assert.deepEqual(filterTerms(entries, 'asc'), [['asce', 'ace']]);
  assert.deepEqual(filterTerms(entries, 'ACE'), [['asce', 'ace']]);
  assert.deepEqual(filterTerms(entries, ''), entries);
});

test('sortTerms orders case-insensitively without mutating', () => {
  const list = ['Zulu', 'apple', 'Fixer'];
  const out = sortTerms(list);
  assert.deepEqual(out, ['apple', 'Fixer', 'Zulu']);
  assert.deepEqual(list, ['Zulu', 'apple', 'Fixer']);
  assert.deepEqual(
    sortTerms([
      ['zulu', 'z'],
      ['Apple', 'a'],
    ]),
    [
      ['Apple', 'a'],
      ['zulu', 'z'],
    ],
  );
});

test('validateTerm accepts good names and phrases', () => {
  assert.equal(validateTerm('names', 'Fixer Upper', null), null);
  assert.equal(validateTerm('phrases', 'Fixer Upper', null), null);
  assert.equal(validateTerm('names', 'Fixer', 'Fixed'), null);
  assert.equal(validateTerm('hard_fixes', 'asce', 'ace'), null);
  assert.equal(validateTerm('hard_fixes', 'marimo', null), null);
});

test('validateTerm rejects empty, non-string, and control-character terms', () => {
  for (const bad of ['', '   ', null, 5, 'has\x07bell']) {
    assert.ok(typeof validateTerm('names', bad, null) === 'string', JSON.stringify(bad));
  }
});

test('validateTerm enforces the 80/120 limits and the phrases space rule', () => {
  assert.ok(validateTerm('names', 'x'.repeat(81), null));
  assert.equal(validateTerm('names', 'x'.repeat(80), null), null);
  assert.ok(validateTerm('phrases', 'x'.repeat(121), null));
  assert.ok(validateTerm('phrases', 'SingleToken', null), 'single tokens belong in names');
  assert.equal(validateTerm('phrases', 'x'.repeat(118) + ' y', null), null);
  assert.ok(validateTerm('hard_fixes', 'x'.repeat(121), 'y'));
});

test('validateTerm rejects hard_fixes keys equal to their value and unknown keys', () => {
  assert.ok(validateTerm('hard_fixes', 'Ace', 'aCE'), 'key unequal to value case-insensitively');
  assert.ok(validateTerm('nope', 'term', null));
});

test('buildOp returns the POST body with expected_version', () => {
  assert.deepEqual(buildOp('One Pace', 'add', 'names', 'Fixer', null, 'v1'), {
    show: 'One Pace',
    op: 'add',
    key: 'names',
    term: 'Fixer',
    value: null,
    expected_version: 'v1',
  });
  assert.deepEqual(buildOp('One Pace', 'update', 'names', 'Fixer', 'Fixed', 'v1').value, 'Fixed');
  assert.deepEqual(buildOp('One Pace', 'update', 'hard_fixes', 'asce', 'ace', 'v9'), {
    show: 'One Pace',
    op: 'update',
    key: 'hard_fixes',
    term: 'asce',
    value: 'ace',
    expected_version: 'v9',
  });
  const del = buildOp('One Pace', 'delete', 'phrases', 'old phrase', 'ignored', 'v2');
  assert.equal(del.term, 'old phrase');
  assert.equal(del.value, null);
});

test('describeError says busy, conflict, unknown show, and invalid in plain sentences', () => {
  assert.equal(describeError(503, {}), 'glossary busy, try again');
  assert.match(describeError(409, { version: 'abc' }), /conflict/i);
  assert.match(describeError(404, { error: 'no such glossary' }), /no such glossary/);
  assert.match(describeError(400, { error: 'too long' }), /too long/);
  assert.equal(typeof describeError(500, {}), 'string');
});

// Client validation mirrors review_glossary.py: NFC-normalize, then refuse control, format, surrogate,
// private-use and line/paragraph separator characters. A plain space and NBSP (Zs) stay allowed.
test('validateTerm measures length after NFC, like the server', () => {
  const decomposed = 'e\u0301'.repeat(41); // 82 UTF-16 units decomposed, 41 once composed
  assert.equal(decomposed.length, 82);
  assert.equal(validateTerm('names', decomposed, null), null, 'composed it is 41 characters');
  assert.ok(validateTerm('names', 'e\u0301'.repeat(81), null), 'still too long once composed');
  assert.equal(validateTerm('hard_fixes', 'caf\u00e9', 'Cafe\u0301s'), null);
});

test('validateTerm refuses invisible and separator characters in terms and values', () => {
  const bad = {
    ZWSP: '\u200b',
    RLO: '\u202e',
    BOM: '\ufeff',
    LS: '\u2028',
    PS: '\u2029',
    private: '\ue000',
    surrogate: '\ud800',
    NEL: '\u0085',
    DEL: '\u007f',
  };
  for (const [name, ch] of Object.entries(bad)) {
    assert.ok(validateTerm('names', `Na${ch}mi`, null), `term ${name}`);
    assert.ok(validateTerm('hard_fixes', 'zorro', `Zo${ch}ro`), `value ${name}`);
  }
});

test('validateTerm still allows ordinary spaces and no-break spaces', () => {
  assert.equal(validateTerm('phrases', 'Going Merry', null), null);
  assert.equal(validateTerm('names', 'Monkey\u00a0D', null), null);
});

test('isDirty is true only when the add form or the open edit row differs from what is saved', () => {
  const clean = { newTerm: '', newValue: '', editTerm: null, editDraft: '', editValue: '', saved: {} };
  assert.equal(isDirty(clean), false);
  assert.equal(isDirty({ ...clean, newTerm: '  ' }), false, 'whitespace is not an edit');
  assert.equal(isDirty({ ...clean, newTerm: 'Nami' }), true);
  assert.equal(isDirty({ ...clean, newValue: 'x' }), true);
  assert.equal(isDirty({ ...clean, editTerm: 'Zoro', editDraft: 'Zoro' }), false, 'opened but unchanged');
  assert.equal(isDirty({ ...clean, editTerm: 'Zoro', editDraft: 'Roronoa' }), true);
  assert.equal(
    isDirty({ ...clean, editTerm: 'lufi', editDraft: 'lufi', editValue: 'Luffy', saved: { lufi: 'Luffy' } }),
    false,
  );
  assert.equal(
    isDirty({
      ...clean,
      editTerm: 'lufi',
      editDraft: 'lufi',
      editValue: 'Luffy-san',
      saved: { lufi: 'Luffy' },
    }),
    true,
  );
});

test('an ApiError keeps its HTTP status and payload so describeError can use them', () => {
  const cases = [
    [503, { error: 'glossary busy' }, /busy/],
    [409, { error: 'version conflict', version: 'abc' }, /conflict/i],
    [404, { error: 'no such glossary' }, /no such glossary/],
    [400, { error: 'term already exists' }, /already exists/],
  ];
  for (const [status, payload, expected] of cases) {
    const exc = new ApiError(payload.error, status, payload);
    assert.ok(exc instanceof Error);
    assert.equal(exc.status, status);
    assert.deepEqual(exc.payload, payload);
    assert.match(describeError(exc.status, exc.payload), expected);
  }
});

test('validateTerm refuses a backslash in names and phrases but allows it in hard-fix values', () => {
  assert.ok(validateTerm('names', 'AC\\DC', null));
  assert.ok(validateTerm('names', 'Zoro', 'Zo\\ro'));
  assert.ok(validateTerm('phrases', 'AC\\DC band', null));
  assert.equal(validateTerm('hard_fixes', 'acdc band', 'AC\\DC'), null);
});

test('filterTerms and sortTerms tolerate duplicates and non-string entries from a hand-edited file', () => {
  const messy = ['Luffy', 'Luffy', 5, null, 'zoro'];
  assert.deepEqual(filterTerms(messy, 'luf'), ['Luffy', 'Luffy']);
  assert.equal(filterTerms(messy, '5').length, 1, 'a number is matched by its text');
  const sorted = sortTerms(messy);
  assert.equal(sorted.length, 5);
  assert.deepEqual(messy, ['Luffy', 'Luffy', 5, null, 'zoro'], 'the input is not mutated');
});
