import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildRequestBody,
  checkShowPick,
  crossesMidnight,
  describeError,
  describeSchedule,
  formatWhen,
  scheduleBody,
  shortId,
  statusClass,
  validateForm,
  validateSchedule,
} from '../src/lib/runs.js';

test('statusClass maps each request status to its token', () => {
  assert.equal(statusClass('pending'), 'info');
  assert.equal(statusClass('running'), 'info');
  assert.equal(statusClass('done'), 'ok');
  assert.equal(statusClass('failed'), 'bad');
  assert.equal(typeof statusClass('bogus'), 'string');
});

test('buildRequestBody trims and omits blanks', () => {
  assert.deepEqual(buildRequestBody({ show: '  One Pace ', season: '', episodeRe: '', requireEng: false }), {
    show: 'One Pace',
  });
  assert.deepEqual(
    buildRequestBody({ show: 'One Pace', season: ' 3 ', episodeRe: 'E05', requireEng: true }),
    { show: 'One Pace', season: 3, episode_re: 'E05', require_eng: 1 },
  );
});

test('validateForm accepts a full and a minimal form', () => {
  assert.equal(validateForm({ show: 'One Pace', season: '3', episodeRe: 'E05' }), null);
  assert.equal(validateForm({ show: 'One Pace', season: '', episodeRe: '' }), null);
});

test('validateForm rejects bad show names', () => {
  for (const show of ['', '   ', 'a/b', 'a\\b', '..', 'a..b', 'has\nnewline', 'a=b', null, 5]) {
    assert.ok(typeof validateForm({ show, season: '', episodeRe: '' }) === 'string', JSON.stringify(show));
  }
});

test('validateForm needs a positive integer season when given', () => {
  for (const season of ['0', '-1', '1.5', 'abc']) {
    assert.ok(validateForm({ show: 'One Pace', season, episodeRe: '' }), season);
  }
  assert.equal(validateForm({ show: 'One Pace', season: '31', episodeRe: '' }), null);
});

test('validateForm caps the regex at 200 chars and needs it to compile', () => {
  assert.ok(validateForm({ show: 'One Pace', season: '', episodeRe: 'x'.repeat(201) }));
  assert.ok(validateForm({ show: 'One Pace', season: '', episodeRe: '(unclosed' }));
  assert.equal(validateForm({ show: 'One Pace', season: '', episodeRe: 'E0*5' }), null);
});

test('describeError separates the two admin problems and names the 409 id', () => {
  assert.match(describeError(403, { error: 'admin writes are disabled' }), /disabled.*REVIEW_ADMIN_TOKEN/);
  assert.match(describeError(403, { error: 'admin token required' }), /enter it below/);
  assert.match(describeError(409, { existing_id: 'abc123' }), /abc123/);
  assert.match(describeError(401, { error: 'a token is required' }), /sign in again/i);
  assert.match(describeError(400, { error: 'show must not be empty' }), /show must not be empty/);
  assert.equal(typeof describeError(500, {}), 'string');
});

test('shortId keeps the trailing hex and formatWhen reads ISO time', () => {
  assert.equal(shortId('20261012T140000Z-a1b2c3d4'), 'a1b2c3d4');
  assert.equal(shortId('abc'), 'abc');
  assert.equal(shortId(''), '');
  assert.ok(formatWhen('2026-10-12T14:00:00+00:00').includes('2026'));
  assert.equal(formatWhen(null), '—');
  assert.equal(formatWhen('not a date'), '—');
});

test('validateSchedule accepts a full window and rejects bad fields', () => {
  assert.equal(
    validateSchedule({ enabled: true, open: '00:00', close: '10:00', tz: 'America/New_York' }),
    null,
  );
  assert.equal(validateSchedule({ enabled: false, open: '00:00', close: '00:00', tz: 'UTC' }), null);
  for (const bad of ['9:00', '24:00', '00:60', 'ab', '']) {
    assert.ok(validateSchedule({ enabled: true, open: bad, close: '10:00', tz: 'UTC' }), bad);
    assert.ok(validateSchedule({ enabled: true, open: '09:00', close: bad, tz: 'UTC' }), bad);
  }
  assert.ok(validateSchedule({ enabled: true, open: '09:00', close: '17:00', tz: '' }));
  assert.ok(validateSchedule({ enabled: true, open: '09:00', close: '17:00', tz: 'Mars/Olympus' }));
  assert.ok(validateSchedule({ enabled: 'yes', open: '09:00', close: '17:00', tz: 'UTC' }));
});

test('crossesMidnight compares zero-padded times', () => {
  assert.equal(crossesMidnight('22:00', '06:00'), true);
  assert.equal(crossesMidnight('09:00', '17:00'), false);
  assert.equal(crossesMidnight('09:00', '09:00'), false);
});

test('describeSchedule previews the window in one sentence', () => {
  assert.match(
    describeSchedule({ enabled: true, open: '00:00', close: '10:00', tz: 'America/New_York' }),
    /Runs only between 00:00 and 10:00 America\/New_York; requests wait outside that window/,
  );
  assert.match(
    describeSchedule({ enabled: true, open: '22:00', close: '06:00', tz: 'UTC' }),
    /Window crosses midnight/,
  );
  assert.ok(
    !describeSchedule({ enabled: true, open: '09:00', close: '17:00', tz: 'UTC' }).includes('midnight'),
  );
  assert.match(describeSchedule({ enabled: false, open: '00:00', close: '00:00', tz: 'UTC' }), /off/i);
});

test('scheduleBody trims strings and keeps the boolean', () => {
  assert.deepEqual(scheduleBody({ enabled: true, open: ' 09:00 ', close: '17:00 ', tz: ' UTC ' }), {
    enabled: true,
    open: '09:00',
    close: '17:00',
    tz: 'UTC',
  });
});

test('checkShowPick requires a listed show when the list is known, and allows free text when it is not', () => {
  assert.equal(checkShowPick('Neon Harbor', ['Alpha', 'Neon Harbor']), null);
  assert.equal(checkShowPick('  Neon Harbor ', ['Neon Harbor']), null);
  assert.match(checkShowPick('Neon', ['Neon Harbor']), /Pick a show from the list/);
  assert.equal(checkShowPick('Anything', []), null);
  // Show directories are case-sensitive on the server: a case-only match is refused, never sent as typed.
  assert.match(checkShowPick('one piece', ['One Piece']), /Pick a show from the list/);
});
