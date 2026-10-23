import test from 'node:test';
import assert from 'node:assert/strict';
import {
  categoryRows,
  describeRow,
  displayValue,
  loadShowAdvanced,
  readOnlyReason,
  saveShowAdvanced,
} from '../src/lib/settingsModel.js';

const SCHEMA = {
  settings: [
    {
      key: 'REQUIRE_ENG',
      category: 'library',
      type: 'bool',
      editable: true,
      advanced: false,
      applies: 'next_show',
    },
    {
      key: 'WHISPER_BEAM_SIZE',
      category: 'transcription',
      type: 'int',
      editable: true,
      advanced: false,
      applies: 'next_show',
      min: 1,
      max: 20,
    },
    {
      key: 'ACQUIRE_MIN_SIM',
      category: 'glossary',
      type: 'float',
      editable: true,
      advanced: true,
      applies: 'next_show',
    },
    {
      key: 'MINE_MIN_COUNT',
      category: 'glossary',
      type: 'int',
      editable: true,
      advanced: false,
      applies: 'next_show',
    },
    {
      key: 'VERIFY_TIMEOUT',
      category: 'glossary',
      type: 'int',
      editable: false,
      advanced: true,
      applies: 'next_show',
    },
    {
      key: 'CONFIG_DIR',
      category: 'general',
      type: 'string',
      editable: false,
      advanced: false,
      managed_by: 'bootstrap',
      applies: 'restart',
    },
    {
      key: 'REVIEW_PORT',
      category: 'general',
      type: 'int',
      editable: true,
      advanced: false,
      applies: 'restart',
    },
    {
      key: 'PLEX_TOKEN',
      category: 'connect',
      type: 'secret',
      secret: true,
      editable: true,
      advanced: false,
      applies: 'next_show',
    },
    {
      key: 'PLEX_URL',
      category: 'connect',
      type: 'url',
      editable: true,
      advanced: false,
      applies: 'next_show',
    },
  ],
};
const LOADED = {
  REQUIRE_ENG: { value: true, source: 'default' },
  WHISPER_BEAM_SIZE: { value: 7, source: 'ui', overridden_env: true },
  MINE_MIN_COUNT: { value: 3, source: 'default' },
  PLEX_TOKEN: { set: false, source: 'default' },
  PLEX_URL: { value: '', source: 'default' },
};

test('a category lists its own settings in registry order', () => {
  assert.deepEqual(
    categoryRows(SCHEMA, 'glossary', true).rows.map((r) => r.key),
    ['ACQUIRE_MIN_SIM', 'MINE_MIN_COUNT', 'VERIFY_TIMEOUT'],
  );
  assert.deepEqual(categoryRows(SCHEMA, 'nope', true), { rows: [], bootstrap: [] });
  assert.deepEqual(categoryRows(null, 'glossary', true), { rows: [], bootstrap: [] });
});

test('bootstrap values always list, in their own section, only in their category', () => {
  const general = categoryRows(SCHEMA, 'general', false);
  assert.deepEqual(
    general.bootstrap.map((r) => r.key),
    ['CONFIG_DIR'],
  );
  assert.deepEqual(
    general.rows.map((r) => r.key),
    ['REVIEW_PORT'],
  );
  assert.deepEqual(categoryRows(SCHEMA, 'library', true).bootstrap, []);
});

test('a row is read-only for the spec reasons, and editable otherwise', () => {
  const by = Object.fromEntries(SCHEMA.settings.map((s) => [s.key, s]));
  assert.equal(readOnlyReason(by.VERIFY_TIMEOUT, {}), 'edit in a later release');
  assert.equal(readOnlyReason(by.CONFIG_DIR, {}), 'Set in the container environment');
  assert.equal(readOnlyReason({ managed_by: 'connections' }, {}), 'Set through a Connection');
  assert.equal(readOnlyReason(by.PLEX_TOKEN, { secretsWritable: false }), 'available after login is enabled');
  assert.equal(readOnlyReason(by.PLEX_TOKEN, { secretsWritable: true }), '');
  assert.equal(readOnlyReason(by.REQUIRE_ENG, {}), '');
});

test('describeRow carries source, the overrides-env flag and the restart label', () => {
  const row = describeRow(SCHEMA.settings[1], LOADED.WHISPER_BEAM_SIZE, {});
  assert.deepEqual(
    [row.sourceLabel, row.overridesEnv, row.restart, row.editable],
    ['Set here', true, false, true],
  );
  assert.equal(describeRow(SCHEMA.settings[6], { value: 8842, source: 'env' }, {}).restart, true);
});

test('displayValue shows secrets only as Set or Not set and booleans as On or Off', () => {
  assert.equal(displayValue({ type: 'secret', isSet: true, value: 'leaked' }), 'Set');
  assert.equal(displayValue({ type: 'secret', isSet: false }), 'Not set');
  assert.equal(displayValue({ type: 'bool', value: false }), 'Off');
  assert.equal(displayValue({ type: 'string', value: '' }), 'Not set');
  assert.equal(displayValue({ type: 'int', value: 7 }), '7');
  assert.equal(displayValue({ type: 'string', value: 'x'.repeat(200) }).length, 121);
});

test('Show Advanced is persisted and survives a storage that throws', () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(loadShowAdvanced(storage), false);
  saveShowAdvanced(storage, true);
  assert.equal(loadShowAdvanced(storage), true);
  saveShowAdvanced(storage, false);
  assert.equal(loadShowAdvanced(storage), false);
  const broken = {
    getItem: () => {
      throw new Error('denied');
    },
    setItem: () => {
      throw new Error('denied');
    },
  };
  assert.equal(loadShowAdvanced(broken), false);
  assert.doesNotThrow(() => saveShowAdvanced(broken, true));
  assert.equal(loadShowAdvanced(null), false);
});

test('advanced rows are not listed while Show Advanced is off, and appear when it is on', () => {
  assert.deepEqual(
    categoryRows(SCHEMA, 'glossary', false).rows.map((r) => r.key),
    ['MINE_MIN_COUNT'],
  );
  assert.deepEqual(
    categoryRows(SCHEMA, 'glossary', true).rows.map((r) => r.key),
    ['ACQUIRE_MIN_SIM', 'MINE_MIN_COUNT', 'VERIFY_TIMEOUT'],
  );
});

test('a role that cannot edit sees every row read-only, with the reason', () => {
  const entry = SCHEMA.settings.find((s) => s.key === 'WHISPER_BEAM_SIZE');
  assert.equal(readOnlyReason(entry, { canEdit: false }), 'Only an admin can change settings');
  assert.equal(readOnlyReason(entry, { canEdit: true }), '');
  assert.equal(readOnlyReason(entry, {}), '');
  assert.equal(describeRow(entry, { value: 7, source: 'default' }, { canEdit: false }).editable, false);
  const later = SCHEMA.settings.find((s) => s.key === 'VERIFY_TIMEOUT');
  assert.equal(
    readOnlyReason(later, { canEdit: false }),
    'edit in a later release',
    'the first-wave rule comes first',
  );
});

test('every bootstrap value lists under General, whatever category the registry gives it', () => {
  const schema = {
    settings: [
      ...SCHEMA.settings,
      {
        key: 'LONGCATAI_API_KEY',
        category: 'connections',
        type: 'secret',
        secret: true,
        editable: false,
        advanced: false,
        managed_by: 'bootstrap',
        applies: 'next_show',
      },
    ],
  };
  assert.deepEqual(
    categoryRows(schema, 'general', false).bootstrap.map((r) => r.key),
    ['CONFIG_DIR', 'LONGCATAI_API_KEY'],
  );
  assert.deepEqual(categoryRows(schema, 'connections', true), { rows: [], bootstrap: [] });
});

const APPLY_ENTRY = { key: 'ACQUIRE_APPLY', type: 'bool', editable: true, applies: 'next_show' };

test('describeRow turns each applies value into its takes-effect text', () => {
  const cases = {
    next_show: 'Takes effect from the next show',
    next_episode: 'Takes effect from the next episode',
    next_merge_pass: 'Takes effect at the next merge pass',
    next_sweep: 'Takes effect at the next library sweep',
  };
  for (const [applies, text] of Object.entries(cases)) {
    const row = describeRow({ ...APPLY_ENTRY, applies }, { value: true }, { canEdit: true });
    assert.equal(row.takesEffect, text, applies);
    assert.equal(row.restart, false, applies);
  }
});

test('describeRow gives a restart row no takes-effect text and keeps its restart flag', () => {
  const row = describeRow({ ...APPLY_ENTRY, applies: 'restart' }, { value: true }, { canEdit: true });
  assert.equal(row.restart, true);
  assert.equal(row.takesEffect, '');
});

test('describeRow warns once and returns empty text for a missing or unknown applies', () => {
  const warnings = [];
  const original = console.warn;
  console.warn = (...args) => warnings.push(args.join(' '));
  try {
    const unknown = describeRow({ ...APPLY_ENTRY, applies: 'someday' }, { value: true }, {});
    assert.equal(unknown.takesEffect, '');
    assert.equal(warnings.length, 1);
    assert.match(warnings[0], /ACQUIRE_APPLY/);
    assert.match(warnings[0], /someday/);

    const noApplies = { ...APPLY_ENTRY };
    delete noApplies.applies;
    const missing = describeRow(noApplies, { value: true }, {});
    assert.equal(missing.takesEffect, '');
    assert.equal(warnings.length, 2);
    assert.match(warnings[1], /ACQUIRE_APPLY/);
  } finally {
    console.warn = original;
  }
});

test('describeRow gives a bootstrap-managed row no takes-effect text and no warning', () => {
  const warnings = [];
  const original = console.warn;
  console.warn = (...args) => warnings.push(args.join(' '));
  try {
    const entry = {
      key: 'LONGCATAI_API_KEY',
      type: 'secret',
      secret: true,
      editable: false,
      managed_by: 'bootstrap',
      applies: 'next_show',
    };
    assert.equal(describeRow(entry, { set: true }, {}).takesEffect, '');
    assert.equal(describeRow({ ...entry, applies: undefined }, { set: true }, {}).takesEffect, '');
    assert.deepEqual(warnings, []);
  } finally {
    console.warn = original;
  }
});
