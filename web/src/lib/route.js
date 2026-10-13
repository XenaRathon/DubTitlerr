// Hash routing for the review workspace: the location hash names a view, nothing else.
// Pure, so node:test can import it without a browser.

export const VIEWS = /** @type {const} */ (['inbox', 'shared', 'dashboard', 'glossary', 'runs', 'settings']);

/**
 * The view a location hash names. Empty, bare and unknown hashes fall back to the inbox.
 * @param {string | null | undefined} hash
 * @returns {'inbox' | 'shared' | 'dashboard' | 'glossary' | 'runs' | 'settings'}
 */
export function parseHash(hash) {
  const name = String(hash ?? '')
    .replace(/^#\/?/, '')
    .split(/[/?]/, 1)[0];
  return VIEWS.find((v) => v === name) ?? 'inbox';
}

/**
 * The canonical hash for a view; an unknown view gets the inbox hash.
 * @param {string | null | undefined} view
 */
export function hashFor(view) {
  return '#/' + (VIEWS.find((v) => v === view) ?? 'inbox');
}
