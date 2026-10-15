/* global Headers */
import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../src/lib/api.js';
import {
  CSRF_HEADER,
  apiFetch,
  changePassword,
  login,
  logout,
  me,
  request,
  setupAccount,
} from '../src/lib/session.js';

function fakeFetch(...replies) {
  const calls = [];
  globalThis.fetch = async (path, init = {}) => {
    calls.push({ path, init });
    const r = replies.shift() ?? { status: 200, body: {} };
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
  return calls;
}

test('every request that is not a GET carries the CSRF header, and a GET does not', async () => {
  const calls = fakeFetch({ status: 200 }, { status: 200 }, { status: 200 }, { status: 200 });
  await apiFetch('/api/episodes');
  await apiFetch('/api/decide', { method: 'POST' });
  await apiFetch('/api/settings', { method: 'put' });
  await apiFetch('/api/users/a', { method: 'DELETE', headers: { 'X-Other': '1' } });
  const has = (i) => new Headers(calls[i].init.headers).has(CSRF_HEADER);
  assert.deepEqual([has(0), has(1), has(2), has(3)], [false, true, true, true]);
  assert.equal(new Headers(calls[3].init.headers).get('X-Other'), '1');
  assert.equal(calls[0].init.credentials, 'same-origin');
});

test('no call ever sends a token header', async () => {
  const calls = fakeFetch(
    { status: 200, body: { username: 'a', role: 'user' } },
    { status: 200, body: {} },
    { status: 200, body: {} },
  );
  await me();
  await login({ username: 'a', password: 'b' });
  await logout();
  for (const c of calls) {
    const names = [...new Headers(c.init.headers).keys()];
    assert.ok(!names.includes('x-review-token') && !names.includes('x-review-admin-token'), c.path);
  }
});

test('request returns the JSON and throws an ApiError that keeps status and payload', async () => {
  fakeFetch(
    { status: 200, body: { ok: 1 } },
    { status: 403, body: { error: 'admin only' } },
    { status: 200, body: { error: 'boom' } },
  );
  assert.deepEqual(await request('/api/x'), { ok: 1 });
  await assert.rejects(
    request('/api/x', { method: 'POST', body: {} }),
    (e) => e instanceof ApiError && e.status === 403 && e.message === 'admin only',
  );
  await assert.rejects(request('/api/x'), (e) => e instanceof ApiError && e.payload.error === 'boom');
});

test('login posts the credentials as JSON with remember defaulting to false', async () => {
  const calls = fakeFetch({ status: 200, body: { username: 'Reviewer', role: 'admin' } });
  assert.deepEqual(await login({ username: 'reviewer', password: 'pw pw pw pw pw' }), {
    username: 'Reviewer',
    role: 'admin',
  });
  assert.equal(calls[0].path, '/api/login');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    username: 'reviewer',
    password: 'pw pw pw pw pw',
    remember: false,
  });
  assert.equal(new Headers(calls[0].init.headers).get('Content-Type'), 'application/json');
});

test('a throttled login keeps retry_after on the error', async () => {
  fakeFetch({ status: 429, body: { error: 'too many failed logins', retry_after: 60 } });
  await assert.rejects(
    login({ username: 'a', password: 'b' }),
    (e) => e.status === 429 && e.payload.retry_after === 60,
  );
});

test('me tells setup, login and signed-in apart', async () => {
  fakeFetch(
    { status: 409, body: { error: 'setup required' } },
    { status: 401, body: { error: 'login required' } },
    { status: 200, body: { username: 'a', role: 'user' } },
  );
  assert.deepEqual(await me(), { state: 'setup' });
  assert.deepEqual(await me(), { state: 'login' });
  assert.deepEqual(await me(), { state: 'in', username: 'a', role: 'user' });
});

test('me throws on anything else', async () => {
  fakeFetch({ status: 500, body: { error: 'down' } });
  await assert.rejects(me(), (e) => e.status === 500);
});

test('logout, setup and change-password use their routes and methods', async () => {
  const calls = fakeFetch(
    { status: 200, body: { ok: true } },
    { status: 200, body: { username: 'boss', role: 'admin' } },
    { status: 200, body: { ok: true } },
  );
  await logout();
  await setupAccount({ username: 'boss', password: 'a long enough pass' });
  await changePassword({ current: 'old old old old', next: 'new new new new' });
  assert.deepEqual(
    calls.map((c) => [c.init.method, c.path]),
    [
      ['POST', '/api/logout'],
      ['POST', '/api/setup'],
      ['PUT', '/api/me/password'],
    ],
  );
  assert.deepEqual(JSON.parse(calls[1].init.body), { username: 'boss', password: 'a long enough pass' });
  assert.deepEqual(JSON.parse(calls[2].init.body), { current: 'old old old old', new: 'new new new new' });
});

test('headers given as a Headers instance or as pairs survive, and a POST still gets the CSRF header', async () => {
  const calls = fakeFetch({ status: 200 }, { status: 200 });
  await apiFetch('/api/a', { method: 'POST', headers: new Headers({ 'X-Other': '1' }) });
  await apiFetch('/api/b', { method: 'POST', headers: [['X-Pair', '2']] });
  const h0 = new Headers(calls[0].init.headers);
  const h1 = new Headers(calls[1].init.headers);
  assert.equal(h0.get('X-Other'), '1');
  assert.equal(h0.get(CSRF_HEADER), '1');
  assert.equal(h1.get('X-Pair'), '2');
  assert.equal(h1.get(CSRF_HEADER), '1');
});
