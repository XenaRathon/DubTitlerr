import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CLEAR,
  blankConnection,
  connectionsBody,
  connectionsChanged,
  describeTestResult,
  parseExtraBody,
  stageChoices,
  stagesBody,
} from '../src/lib/settingsModel.js';

const RULES = {
  kinds: ['llamacpp', 'ollama', 'openai'],
  stages: [
    { id: 'repair', kinds: ['llamacpp', 'ollama', 'openai'] },
    { id: 'restore', kinds: ['llamacpp', 'ollama'] },
    { id: 'verify', kinds: ['llamacpp', 'ollama', 'openai'] },
    { id: 'decision', kinds: ['openai'] },
  ],
  via_decision: '@decision',
  timeout_defaults: { timeout_connect: 10, timeout_read: 120 },
};
const CONNS = [
  {
    name: 'local',
    kind: 'llamacpp',
    url: 'http://h/v1',
    model: 'm',
    extra_body: { set: false },
    timeout_connect: 10,
    timeout_read: 120,
    api_key: { set: false },
  },
  {
    name: 'cloud',
    kind: 'openai',
    url: 'https://h/v1',
    model: 'g',
    extra_body: { set: true },
    model_secondary: 'g-mini',
    timeout_connect: 10,
    timeout_read: 120,
    api_key: { set: true },
  },
];

test('a stage lists only the connections of an accepted kind, and verify may follow the decision stage', () => {
  assert.deepEqual(
    stageChoices(RULES, 'restore', CONNS).map((c) => c.value),
    ['local'],
  );
  assert.deepEqual(
    stageChoices(RULES, 'decision', CONNS).map((c) => c.value),
    ['cloud'],
  );
  assert.deepEqual(
    stageChoices(RULES, 'verify', CONNS).map((c) => c.value),
    ['local', 'cloud', '@decision'],
  );
  assert.deepEqual(
    stageChoices(RULES, 'repair', [{ name: '', kind: 'llamacpp' }]),
    [],
    'an unnamed new row is not a choice yet',
  );
});

test('a new connection starts with the server default timeouts and no key', () => {
  const blank = blankConnection(RULES);
  assert.deepEqual(
    [blank.kind, blank.timeout_connect, blank.timeout_read, blank.api_key.set],
    ['llamacpp', 10, 120, false],
  );
});

test('the extra body box accepts an empty box or a JSON object and says why not otherwise', () => {
  assert.deepEqual(parseExtraBody('  '), { value: {}, error: '' });
  assert.deepEqual(parseExtraBody('{"a": 1}'), { value: { a: 1 }, error: '' });
  assert.equal(parseExtraBody('[1]').value, null);
  assert.equal(parseExtraBody('{oops').error, 'Not valid JSON.');
});

test('connectionsBody sends a key only when it was touched, and never invents one', () => {
  const body = connectionsBody([
    { ...CONNS[0] },
    { ...CONNS[1], key: 'sk-new' },
    { ...CONNS[1], name: 'c2', key: CLEAR },
    { ...CONNS[1], name: 'c3', key: '' },
  ]);
  assert.equal('api_key' in body[0], false);
  assert.equal(body[1].api_key, 'sk-new');
  assert.deepEqual(body[2].api_key, { clear: true });
  assert.equal('api_key' in body[3], false);
  assert.equal('key' in body[1], false);
});

test('connectionsChanged sees an edited field or a typed key, not a re-render', () => {
  assert.equal(
    connectionsChanged(
      CONNS,
      CONNS.map((c) => ({ ...c })),
    ),
    false,
  );
  assert.equal(connectionsChanged(CONNS, [{ ...CONNS[0], url: 'http://other/v1' }, CONNS[1]]), true);
  assert.equal(connectionsChanged(CONNS, [CONNS[0], { ...CONNS[1], key: 'sk' }]), true);
  assert.equal(connectionsChanged(CONNS, [CONNS[0]]), true);
});

test('stagesBody lists only the picks that moved, with null for a removed pick', () => {
  assert.equal(stagesBody({ repair: 'local' }, { repair: 'local' }), null);
  assert.deepEqual(stagesBody({ repair: 'local' }, { repair: 'cloud', verify: 'local' }), {
    repair: 'cloud',
    verify: 'local',
  });
  assert.deepEqual(stagesBody({ repair: 'local' }, { repair: '' }), { repair: null });
  assert.equal(stagesBody(undefined, undefined), null);
});

test('a test result reads as one plain sentence', () => {
  assert.equal(describeTestResult({ ok: true, latency_ms: 42 }), 'Connection ok in 42 ms.');
  assert.equal(describeTestResult({ ok: false, error: 'connection refused' }), 'connection refused');
  assert.equal(describeTestResult({ ok: false, error: '' }), 'Connection failed.');
  assert.equal(
    describeTestResult({ ok: false, error: 'slow down', status: 429 }),
    'Too many checks. Wait a moment and retry.',
  );
  assert.equal(
    describeTestResult({ ok: false, error: 'boom', status: 502 }),
    'The test failed (HTTP 502): boom',
  );
  assert.equal(describeTestResult(null), 'Connection failed.');
});

test('a stored extra body travels back as the {set} marker, so the server keeps it', () => {
  const [local, cloud] = connectionsBody(CONNS.map((c) => ({ ...c })));
  assert.deepEqual(cloud.extra_body, { set: true });
  assert.deepEqual(local.extra_body, {}, 'a llama.cpp connection never carries a body');
  assert.equal(cloud.model_secondary, 'g-mini', 'the secondary model survives a save');
});

test('a replaced extra body is sent as the new object; a non-OpenAI connection sends none', () => {
  const [, cloud] = connectionsBody([
    CONNS[0],
    { ...CONNS[1], extra_body: { reasoning: { effort: 'low' } } },
  ]);
  assert.deepEqual(cloud.extra_body, { reasoning: { effort: 'low' } });
  const [switched] = connectionsBody([{ ...CONNS[1], kind: 'llamacpp' }]);
  assert.deepEqual(switched.extra_body, {}, 'a body is used only by OpenAI-compatible connections');
  assert.equal(connectionsChanged(CONNS, [CONNS[0], { ...CONNS[1], extra_body: {} }]), true);
});
