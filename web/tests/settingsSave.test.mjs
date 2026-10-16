import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CLEAR,
  RESET,
  buildValues,
  describeSaveError,
  fieldErrors,
  isDirty,
  isSaveShortcut,
  saveLabel,
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

test('buildValues sends only what differs from the loaded page', () => {
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, {}), {});
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { WHISPER_BEAM_SIZE: '7' }), {});
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { WHISPER_BEAM_SIZE: '5', REQUIRE_ENG: false }), {
    WHISPER_BEAM_SIZE: 5,
    REQUIRE_ENG: false,
  });
  assert.deepEqual(
    buildValues(SCHEMA.settings, LOADED, { REQUIRE_ENG: true }),
    {},
    'an unchanged value that nobody stored is not a save',
  );
});

test('buildValues turns the pages gestures into the API forms', () => {
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { WHISPER_BEAM_SIZE: RESET }), {
    WHISPER_BEAM_SIZE: null,
  });
  assert.deepEqual(
    buildValues(SCHEMA.settings, LOADED, { MINE_MIN_COUNT: RESET }),
    {},
    'nothing stored, nothing to reset',
  );
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { PLEX_TOKEN: 'tok-123' }), {
    PLEX_TOKEN: 'tok-123',
  });
  assert.deepEqual(
    buildValues(SCHEMA.settings, LOADED, { PLEX_TOKEN: '' }),
    {},
    'an empty secret field means no change',
  );
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { PLEX_TOKEN: CLEAR }), {
    PLEX_TOKEN: { clear: true },
  });
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { PLEX_URL: ' http://plex.lan:32400 ' }), {
    PLEX_URL: 'http://plex.lan:32400',
  });
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { MINE_MIN_COUNT: '' }), { MINE_MIN_COUNT: null });
});

test('a number field that is not a number goes to the server as text so the server names the problem', () => {
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { WHISPER_BEAM_SIZE: 'lots' }), {
    WHISPER_BEAM_SIZE: 'lots',
  });
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { WHISPER_BEAM_SIZE: '5.5' }), {
    WHISPER_BEAM_SIZE: '5.5',
  });
  assert.deepEqual(buildValues(SCHEMA.settings, LOADED, { ACQUIRE_MIN_SIM: '0.8' }), {
    ACQUIRE_MIN_SIM: 0.8,
  });
});

test('the save button reads No Changes until something differs, and Ctrl or Cmd S is the shortcut', () => {
  assert.equal(saveLabel(false), 'No Changes');
  assert.equal(saveLabel(true), 'Save Changes');
  assert.equal(isDirty({}, null, null), false);
  assert.equal(isDirty({ A: 1 }, null, null), true);
  assert.equal(isDirty({}, [], null), true);
  assert.equal(isSaveShortcut({ ctrlKey: true, key: 's' }), true);
  assert.equal(isSaveShortcut({ metaKey: true, key: 'S' }), true);
  assert.equal(isSaveShortcut({ key: 's' }), false);
  assert.equal(isSaveShortcut({ ctrlKey: true, key: 'a' }), false);
});

test('field errors come from the servers errors object and nothing else', () => {
  assert.deepEqual(
    fieldErrors({
      errors: { WHISPER_BEAM_SIZE: 'must be between 1 and 20', 'connections.local.url': 'is required' },
    }),
    {
      WHISPER_BEAM_SIZE: 'must be between 1 and 20',
      'connections.local.url': 'is required',
    },
  );
  for (const bad of [null, undefined, {}, { errors: [] }, { errors: 'x' }, { errors: { A: 3 } }])
    assert.deepEqual(fieldErrors(bad), {});
});

test('save errors that are not field errors are one plain sentence each', () => {
  assert.match(describeSaveError(409, {}), /changed since you opened/);
  assert.match(describeSaveError(503, { error: 'x' }), /busy/);
  assert.match(describeSaveError(507, {}), /full/);
  assert.match(
    describeSaveError(403, { error: 'secrets can be changed only after login is enabled' }),
    /^Secrets can be changed only after login is enabled\.$/,
  );
  assert.match(describeSaveError(400, {}), /red/);
  assert.match(describeSaveError(500, { error: 'boom' }), /boom \(HTTP 500\)/);
});
