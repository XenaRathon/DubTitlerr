/* global Headers */
// Every call the web UI makes to the review API goes through here: the session is an HttpOnly cookie the browser sends
// by itself, and every request that changes something carries X-DubTitlerr-Request (a cross-site form cannot set it).
// No token is stored, read or sent from this module.
import { ApiError } from './api.js';

export const CSRF_HEADER = 'X-DubTitlerr-Request';

/**
 * fetch for the review API.
 * @param {string} path
 * @param {RequestInit} [init]
 */
export function apiFetch(path, init = {}) {
  const method = String(init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== 'GET') headers.set(CSRF_HEADER, '1');
  return fetch(path, { ...init, method, headers, credentials: 'same-origin' });
}

/**
 * One JSON call. Throws an ApiError that keeps the HTTP status and the parsed body.
 * @param {string} path
 * @param {{ method?: string, body?: object }} [opts]
 */
export async function request(path, { method = 'GET', body } = {}) {
  const res = await apiFetch(path, {
    method,
    ...(body === undefined
      ? {}
      : { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.error)
    throw new ApiError(payload.error || `Request failed (${res.status})`, res.status, payload);
  return payload;
}

/** Who this browser is: first-run setup, a login form, or a signed-in account. */
export async function me() {
  const res = await apiFetch('/api/me');
  const payload = await res.json().catch(() => ({}));
  if (res.status === 409) return { state: 'setup' };
  if (res.status === 401) return { state: 'login' };
  if (res.ok && typeof payload.username === 'string')
    return { state: 'in', username: payload.username, role: payload.role };
  throw new ApiError(payload.error || `Request failed (${res.status})`, res.status, payload);
}

/** @param {{ username: string, password: string, remember?: boolean }} credentials */
export const login = ({ username, password, remember = false }) =>
  request('/api/login', { method: 'POST', body: { username, password, remember } });

export const logout = async () => {
  await request('/api/logout', { method: 'POST', body: {} });
};

/** @param {{ username: string, password: string }} account */
export const setupAccount = ({ username, password }) =>
  request('/api/setup', { method: 'POST', body: { username, password } });

/** @param {{ current: string, next: string }} passwords */
export const changePassword = async ({ current, next }) => {
  await request('/api/me/password', { method: 'PUT', body: { current, new: next } });
};
