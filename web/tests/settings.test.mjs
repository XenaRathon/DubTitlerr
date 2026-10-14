import test from 'node:test';
import assert from 'node:assert/strict';
import {
  allowedChoices,
  buildSettingsBody,
  describeAcquireApply,
  describePendingAcquireApply,
  describeTestResult,
  describeWriteError,
  formatValue,
  groupSettings,
  pendingEntries,
  secretBadges,
  sourceNote,
  validateModel,
} from '../src/lib/settings.js';
import { adminHeaders } from '../src/lib/adminToken.js';

const FULL = {
  repair_backend: 'llamacpp',
  repair_model: 'qwen3-4b-instruct',
  repair_llamacpp_url: 'http://127.0.0.1:8090/v1/chat/completions',
  repair_openai_url: '',
  repair_unanchored: '0',
  verify_backend: 'llamacpp',
  verify_decision_model: 'typesafe/jev',
  acquire_backend: '',
  glossary_arc_tags: '',
  whisper_model: 'large-v3',
  compute_type: 'int8',
  require_eng: '1',
  rescan_interval: '300',
  merge_roots: '/a:/b',
  anime_order: 'One Pace',
};

test('groupSettings files every key into the six sections in order', () => {
  const groups = groupSettings(FULL);
  assert.deepEqual(
    groups.map((g) => g.title),
    ['Repair', 'Verify', 'Acquire', 'Transcription', 'Schedule & loop', 'Paths'],
  );
  const repair = groups[0].entries.map((e) => e.key);
  assert.ok(repair.includes('repair_model') && repair.includes('repair_unanchored'));
  assert.ok(groups[4].entries.some((e) => e.key === 'rescan_interval'));
  assert.equal(
    groups.reduce((n, g) => n + g.entries.length, 0),
    Object.keys(FULL).length,
  );
});

test('groupSettings drops empty sections and files unknown keys under Other', () => {
  assert.deepEqual(groupSettings({}), []);
  const groups = groupSettings({ repair_model: 'q', merge_window: '9-5', custom_thing: 'x' });
  assert.deepEqual(
    groups.map((g) => g.title),
    ['Repair', 'Schedule & loop', 'Other'],
  );
  assert.deepEqual(
    groups[1].entries.map((e) => e.key),
    ['merge_window'],
  );
  assert.deepEqual(
    groups[2].entries.map((e) => e.key),
    ['custom_thing'],
  );
});

test('formatValue reports empty values as not set', () => {
  for (const empty of [null, undefined, '', '   ']) {
    assert.equal(formatValue('repair_model', empty), 'not set');
  }
});

test('formatValue says yes and no for booleans and flag strings', () => {
  assert.equal(formatValue('require_eng', true), 'yes');
  assert.equal(formatValue('require_eng', false), 'no');
  assert.equal(formatValue('require_eng', '1'), 'yes');
  assert.equal(formatValue('repair_unanchored', '0'), 'no');
  assert.equal(formatValue('repair_model', 'qwen3-4b-instruct'), 'qwen3-4b-instruct');
});

test('formatValue shortens long lists but passes normal values through', () => {
  assert.equal(formatValue('merge_roots', '/a:/b:/c:/d:/e'), '/a, /b, /c… (+2 more)');
  assert.equal(formatValue('merge_roots', '/a:/b'), '/a:/b');
  assert.equal(formatValue('anime_order', 'One Pace'), 'One Pace');
});

test('secretBadges maps names to set flags, sorted, never values', () => {
  const badges = secretBadges({ REVIEW_TOKEN: 'sk-secret-123', LONGCATAI_API_KEY: '', REVIEW_PASSWORD: 'x' });
  assert.deepEqual(badges, [
    { name: 'LONGCATAI_API_KEY', set: false },
    { name: 'REVIEW_PASSWORD', set: true },
    { name: 'REVIEW_TOKEN', set: true },
  ]);
  assert.ok(!JSON.stringify(badges).includes('sk-secret-123'));
  assert.deepEqual(secretBadges({}), []);
});

test('describeTestResult turns a success into one sentence with latency', () => {
  assert.equal(describeTestResult({ ok: true, latency_ms: 115, error: '' }), 'Connection ok in 115 ms.');
});

test('describeTestResult passes errors through and maps statuses', () => {
  assert.equal(
    describeTestResult({ ok: false, latency_ms: 0, error: 'connection refused' }),
    'connection refused',
  );
  assert.match(describeTestResult({ ok: false, latency_ms: 0, error: 'x', status: 429 }), /wait/i);
  assert.match(describeTestResult({ ok: false, latency_ms: 0, error: 'boom', status: 503 }), /503/);
  assert.match(
    describeTestResult({ ok: false, latency_ms: 0, error: 'Access token not accepted.' }),
    /sign in again/i,
  );
  assert.equal(typeof describeTestResult(null), 'string');
});

test('sourceNote explains effective.env versus env in one sentence', () => {
  assert.match(sourceNote('effective.env'), /builder at sweep start/);
  assert.match(sourceNote('env'), /own environment.*differ from the builder/);
  assert.equal(sourceNote('bogus'), sourceNote('env'));
});

test('formatValue leaves URLs and IPv6 hosts whole', () => {
  assert.equal(
    formatValue('repair_llamacpp_url', 'http://admin:secret123@host:8090/v1'),
    'http://admin:secret123@host:8090/v1',
  );
  assert.equal(formatValue('repair_llamacpp_url', 'http://[::1]:8080'), 'http://[::1]:8080');
});

test('validateModel accepts server-shaped model ids and rejects the rest', () => {
  for (const good of ['q', 'qwen3-4b-instruct', 'org/model:tag', 'a.b_c/d-e:f0']) {
    assert.equal(validateModel(good), null, good);
  }
  assert.ok(validateModel(''));
  assert.ok(validateModel('   '));
  assert.ok(validateModel('-leading-dash'));
  assert.ok(validateModel('.leading-dot'));
  assert.ok(validateModel('has space'));
  assert.ok(validateModel('has\ttab'));
  assert.ok(validateModel('semi;colon'));
  assert.ok(validateModel('shell$(x)'));
  assert.ok(validateModel(`new\nline`));
  assert.ok(validateModel('x'.repeat(129)));
  assert.equal(validateModel('x'.repeat(128)), null);
  assert.ok(validateModel(null));
  assert.ok(validateModel(42));
});

test('buildSettingsBody sends only changed fields', () => {
  const current = { repair_model: 'qwen', verify_backend: 'llamacpp', require_eng: '1' };
  assert.deepEqual(
    buildSettingsBody(current, {
      repair_profile: '',
      repair_model: 'qwen',
      verify_backend: 'llamacpp',
      verify_decision_model: '',
      requireEng: true,
    }),
    {},
  );
  assert.deepEqual(
    buildSettingsBody(current, {
      repair_profile: '',
      repair_model: '  qwen2  ',
      verify_backend: 'llamacpp',
      verify_decision_model: '',
      requireEng: true,
    }),
    { repair_model: 'qwen2' },
  );
  assert.deepEqual(
    buildSettingsBody(current, {
      repair_profile: 'openai',
      repair_model: 'qwen',
      verify_backend: 'llamacpp',
      verify_decision_model: '',
      requireEng: false,
    }),
    { repair_profile: 'openai', require_eng: 0 },
  );
  assert.deepEqual(
    buildSettingsBody(
      { repair_model: 'qwen' },
      {
        repair_profile: '',
        repair_model: '',
        verify_backend: '',
        verify_decision_model: '',
        requireEng: false,
      },
    ),
    { repair_model: null },
  );
});

test('describeWriteError explains auth states and passes validation through', () => {
  assert.match(describeWriteError(401, { error: 'a token is required' }), /sign in again/i);
  assert.match(describeWriteError(403, { error: 'admin writes are disabled' }), /disabled/);
  assert.match(describeWriteError(403, { error: 'admin token required' }), /enter it below/);
  assert.match(describeWriteError(400, { error: 'unknown key: foo' }), /unknown key: foo/);
  assert.match(describeWriteError(500, { error: 'disk full' }), /disk full/);
  assert.equal(typeof describeWriteError(500, {}), 'string');
});

test('pendingEntries lists pending overrides sorted with values', () => {
  assert.deepEqual(pendingEntries({ repair_model: 'qwen2', require_eng: 1 }), [
    { key: 'repair_model', value: 'qwen2' },
    { key: 'require_eng', value: 1 },
  ]);
  assert.deepEqual(pendingEntries({}), []);
  assert.deepEqual(pendingEntries(null), []);
});

test('adminHeaders carries the token or nothing', () => {
  assert.deepEqual(adminHeaders('sekrit'), { 'X-Review-Admin-Token': 'sekrit' });
  assert.deepEqual(adminHeaders(''), {});
});

test('allowedChoices offers only the server list, trimmed and deduplicated', () => {
  assert.deepEqual(allowedChoices(['llamacpp', ' ollama ', 'llamacpp', '', 7, null], ''), [
    { value: 'llamacpp', label: 'llamacpp', disabled: false },
    { value: 'ollama', label: 'ollama', disabled: false },
  ]);
  assert.deepEqual(allowedChoices(undefined, ''), []);
  assert.deepEqual(allowedChoices('llamacpp', ''), []);
});

test('allowedChoices keeps a current value the server no longer allows, but not as a choice', () => {
  // Without it the select would show the wrong value and a save of another field could silently reset it.
  assert.deepEqual(allowedChoices(['llamacpp'], 'openai'), [
    { value: 'llamacpp', label: 'llamacpp', disabled: false },
    { value: 'openai', label: 'openai (current, not allowed on this server)', disabled: true },
  ]);
  assert.deepEqual(allowedChoices(['llamacpp'], 'llamacpp'), [
    { value: 'llamacpp', label: 'llamacpp', disabled: false },
  ]);
  assert.deepEqual(allowedChoices([], 'typesafe/jev'), [
    { value: 'typesafe/jev', label: 'typesafe/jev (current, not allowed on this server)', disabled: true },
  ]);
});

test('describeWriteError keeps the env var name of an allow-list refusal readable', () => {
  const msg = describeWriteError(400, {
    error: 'verify backend not allowed: the operator lists allowed backends in RUNTIME_VERIFY_BACKENDS',
  });
  assert.match(msg, /RUNTIME_VERIFY_BACKENDS/);
  assert.match(msg, /^Not allowed on this server: verify backend/);
});

// --- ACQUIRE_APPLY: unset means apply, so the toggle seeds from the server's effective value, never from the raw string

const EDITED = {
  repair_profile: '',
  repair_model: 'qwen',
  verify_backend: 'llamacpp',
  verify_decision_model: '',
  requireEng: true,
};

test('buildSettingsBody leaves acquire_apply out when the toggle still equals its seed', () => {
  const current = { repair_model: 'old', verify_backend: 'llamacpp', require_eng: '1', acquire_apply: '' };
  const seed = { enabled: true, source: 'default' };
  // Another field changes, the unset (= apply) toggle is untouched: saving must not write acquire_apply=0.
  assert.deepEqual(buildSettingsBody(current, { ...EDITED, acquireApply: true }, seed), { repair_model: 'qwen' });
  assert.deepEqual(buildSettingsBody(current, { ...EDITED, repair_model: 'old', acquireApply: true }, seed), {});
});

test('buildSettingsBody sends acquire_apply as a real boolean when the toggle moves', () => {
  const current = { repair_model: 'qwen', verify_backend: 'llamacpp', require_eng: '1' };
  assert.deepEqual(
    buildSettingsBody(current, { ...EDITED, acquireApply: false }, { enabled: true, source: 'default' }),
    { acquire_apply: false },
  );
  assert.deepEqual(
    buildSettingsBody(current, { ...EDITED, acquireApply: true }, { enabled: false, source: 'runtime' }),
    { acquire_apply: true },
  );
});

test('buildSettingsBody never sends acquire_apply without a server state to compare against', () => {
  const current = { repair_model: 'qwen', verify_backend: 'llamacpp', require_eng: '1' };
  assert.deepEqual(buildSettingsBody(current, { ...EDITED, acquireApply: false }), {});
  assert.deepEqual(buildSettingsBody(current, { ...EDITED, acquireApply: false }, null), {});
});

test('describeAcquireApply names the value, where it came from and when it takes effect', () => {
  assert.match(describeAcquireApply({ enabled: true, source: 'default' }), /on.*default.*next sweep/i);
  assert.match(describeAcquireApply({ enabled: false, source: 'env' }), /off.*environment.*next sweep/i);
  assert.match(describeAcquireApply({ enabled: false, source: 'runtime' }), /off.*runtime file.*next sweep/i);
  assert.match(describeAcquireApply(undefined), /unknown/i);
});

test('formatValue reads the raw acquire_apply string by the shell rule: empty means yes', () => {
  assert.equal(formatValue('acquire_apply', ''), 'yes (default)');
  assert.equal(formatValue('acquire_apply', '1'), 'yes');
  assert.equal(formatValue('acquire_apply', 'off'), 'no');
  assert.equal(formatValue('acquire_apply', 'dry-run'), 'no');
});

test('groupSettings files acquire_apply under Acquire', () => {
  const acquire = groupSettings({ acquire_apply: '', acquire_backend: '' }).find((g) => g.title === 'Acquire');
  assert.deepEqual(acquire.entries.map((e) => e.key), ['acquire_backend', 'acquire_apply']);
});

test('pendingEntries passes a boolean acquire_apply through', () => {
  assert.deepEqual(pendingEntries({ acquire_apply: false }), [{ key: 'acquire_apply', value: false }]);
});

test('describePendingAcquireApply shows the meaning: only an explicit off reads off, unset reads on', () => {
  assert.equal(describePendingAcquireApply(false), 'off');
  assert.equal(describePendingAcquireApply(true), 'on');
  assert.equal(describePendingAcquireApply(null), 'on');
  assert.equal(describePendingAcquireApply(undefined), 'on');
});
