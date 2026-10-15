import test from 'node:test';
import assert from 'node:assert/strict';
import { categoryRows, describeRow, displayValue, readOnlyReason } from '../src/lib/settingsModel.js';

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
