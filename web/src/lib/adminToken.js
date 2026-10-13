/**
 * The single admin-token store shared by every page that writes (Runs, Settings).
 * Tab lifetime only: sessionStorage, never localStorage, never a URL.
 */

export const ADMIN_TOKEN_KEY = 'dubtitlerr_admin_token';

/**
 * The remembered token, or '' when storage is unavailable.
 * @returns {string}
 */
export function loadAdminToken() {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

/**
 * Remember the token for this tab, or forget it when empty.
 * @param {string} token
 */
export function storeAdminToken(token) {
  try {
    if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    /* storage unavailable; the token stays in memory for this page */
  }
}

/** Forget the remembered token. */
export function clearAdminToken() {
  storeAdminToken('');
}

/**
 * The write header for an admin-guarded call, or no header when unset.
 * @param {string} token
 * @returns {Record<string, string>}
 */
export function adminHeaders(token) {
  return token ? { 'X-Review-Admin-Token': token } : {};
}
