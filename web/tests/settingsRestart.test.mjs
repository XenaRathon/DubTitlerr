import test from 'node:test';
import assert from 'node:assert/strict';
import { RESTART_TIMEOUT_MS, describeRestartWait, restartStep } from '../src/lib/settingsModel.js';

test('the restart overlay ends only on a different boot id, and gives up after ten minutes', () => {
  const base = { oldBootId: 'a', startedAt: 1000, now: 2000 };
  assert.equal(restartStep({ ...base, status: { boot_id: 'a' } }), 'waiting', 'the old server still answers');
  assert.equal(restartStep({ ...base, status: null }), 'waiting', 'no answer yet');
  assert.equal(restartStep({ ...base, status: { boot_id: '' } }), 'waiting');
  assert.equal(restartStep({ ...base, status: { boot_id: 'b' } }), 'back');
  assert.equal(restartStep({ ...base, now: 1000 + RESTART_TIMEOUT_MS, status: { boot_id: 'a' } }), 'timeout');
  assert.equal(restartStep({ ...base, now: 1000 + RESTART_TIMEOUT_MS, status: { boot_id: 'b' } }), 'back');
  assert.equal(RESTART_TIMEOUT_MS, 600000);
});

test('the overlay line reports the last heartbeat when the status has one', () => {
  assert.equal(
    describeRestartWait({ header: { builder_heartbeat_age_s: 12.4 } }),
    'Last builder heartbeat 12 s ago.',
  );
  assert.equal(describeRestartWait(null), 'Waiting for the builder to come back.');
});

test('a heartbeat age from a clock that runs ahead is never shown as negative', () => {
  assert.equal(
    describeRestartWait({ header: { builder_heartbeat_age_s: -3.6 } }),
    'Last builder heartbeat 0 s ago.',
  );
  assert.equal(
    describeRestartWait({ header: { builder_heartbeat_age_s: -0.2 } }),
    'Last builder heartbeat 0 s ago.',
  );
});
