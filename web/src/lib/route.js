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

/** The settings categories in sidebar order. tests/test_settings_registry.py checks this list against settings_registry.CATEGORIES. */
export const SETTINGS_CATEGORIES = /** @type {const} */ ([
  { id: 'general', label: 'General' },
  { id: 'library', label: 'Library' },
  { id: 'transcription', label: 'Transcription' },
  { id: 'glossary', label: 'Glossary' },
  { id: 'repair', label: 'Repair' },
  { id: 'connections', label: 'Connections' },
  { id: 'output', label: 'Output' },
  { id: 'schedule', label: 'Schedule' },
  { id: 'connect', label: 'Connect' },
]);

/**
 * The settings category a hash names ('#/settings/library' is 'library'); '' for the card grid, a bare '#/settings' or any
 * other view or unknown category.
 * @param {string | null | undefined} hash
 * @returns {string}
 */
export function parseSettingsCategory(hash) {
  const parts = String(hash ?? '')
    .replace(/^#\/?/, '')
    .split('?', 1)[0]
    .split('/');
  if (parts[0] !== 'settings') return '';
  return SETTINGS_CATEGORIES.find((c) => c.id === parts[1])?.id ?? '';
}

/**
 * The hash of the settings card grid, or of one category page.
 * @param {string | null | undefined} category
 */
export function settingsHash(category) {
  const known = SETTINGS_CATEGORIES.find((c) => c.id === category);
  return known ? `#/settings/${known.id}` : '#/settings';
}

/**
 * The canonical form of a location hash: the view's own hash, except that a settings category page keeps its category.
 * @param {string | null | undefined} hash
 */
export function canonicalHash(hash) {
  const view = parseHash(hash);
  return view === 'settings' ? settingsHash(parseSettingsCategory(hash)) : hashFor(view);
}
