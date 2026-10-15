import test from 'node:test';
import assert from 'node:assert/strict';
import { isAdmin } from '../src/lib/roles.js';

test('only the admin role unlocks admin controls', () => {
  assert.equal(isAdmin('admin'), true);
  for (const role of ['user', '', 'Admin', 'root', undefined, null, 1, {}])
    assert.equal(isAdmin(role), false, String(role));
});
