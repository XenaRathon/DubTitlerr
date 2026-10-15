/** Pure helpers for the category settings pages (specs/webui-full-settings, S-9 to S-13). No DOM, no fetch. */

// --- Rows (S-9, S-13) -------------------------------------------------------------------------------------------------------

/**
 * The rows of one category page, in registry order. Advanced rows are left out entirely (not hidden) while Show Advanced is off;
 * the bootstrap values always list, in their own section, because the operator needs to see what the container fixes.
 * @param {{ settings: Array<any> } | null | undefined} schema
 * @param {string} category
 * @param {boolean} showAdvanced
 */
export function categoryRows(schema, category, showAdvanced) {
  const inCategory = (schema?.settings ?? []).filter((s) => s.category === category);
  return {
    rows: inCategory.filter((s) => s.managed_by !== 'bootstrap' && (showAdvanced || !s.advanced)),
    bootstrap: inCategory.filter((s) => s.managed_by === 'bootstrap'),
  };
}

/**
 * Why a row cannot be edited, or '' when it can. The wording of the first-wave rule is the spec's.
 * @param {any} entry
 * @param {{ secretsWritable?: boolean } | null | undefined} ctx
 * @returns {string}
 */
export function readOnlyReason(entry, ctx) {
  if (entry.managed_by === 'bootstrap') return 'Set in the container environment';
  if (entry.managed_by === 'connections') return 'Set through a Connection';
  if (entry.managed_by === 'retired') return 'Retired: no longer read';
  if (!entry.editable) return 'edit in a later release';
  if (entry.secret && !ctx?.secretsWritable) return 'available after login is enabled';
  return '';
}

// --- Show Advanced (S-10) ---------------------------------------------------------------------------------------------------

export const SHOW_ADVANCED_KEY = 'dubtitlerr.settings.showAdvanced';

/**
 * @param {{ getItem(key: string): string | null } | null | undefined} storage
 * @returns {boolean}
 */
export function loadShowAdvanced(storage) {
  try {
    return storage?.getItem(SHOW_ADVANCED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * @param {{ setItem(key: string, value: string): void } | null | undefined} storage
 * @param {boolean} on
 */
export function saveShowAdvanced(storage, on) {
  try {
    storage?.setItem(SHOW_ADVANCED_KEY, on ? '1' : '0');
  } catch {
    /* storage unavailable (private mode): the toggle still works for this page view */
  }
}

// --- Editing and saving (S-11) ----------------------------------------------------------------------------------------------

/** A draft value that means "remove my stored value, go back to the container value or the default". */
export const RESET = Symbol('reset');
/** A draft value that means "clear this stored secret". */
export const CLEAR = Symbol('clear');

/**
 * The PUT /api/settings `values` for the edited rows: only rows whose draft differs from what the page loaded. A secret draft is
 * the typed string (empty means no change) or CLEAR. RESET sends null.
 * @param {Array<any>} entries schema settings
 * @param {Record<string, any>} loaded GET values
 * @param {Record<string, any>} drafts key -> draft
 * @returns {Record<string, unknown>}
 */
export function buildValues(entries, loaded, drafts) {
  /** @type {Record<string, unknown>} */
  const out = {};
  const byKey = new Map(entries.map((e) => [e.key, e]));
  for (const [key, draft] of Object.entries(drafts)) {
    const entry = byKey.get(key);
    if (!entry) continue;
    const current = loaded[key] ?? {};
    if (entry.type === 'secret') {
      if (draft === CLEAR) out[key] = { clear: true };
      else if (typeof draft === 'string' && draft !== '') out[key] = draft;
      continue;
    }
    if (draft === RESET) {
      if (current.source === 'ui') out[key] = null;
      continue;
    }
    const value = coerce(entry, draft);
    if (value !== current.value) out[key] = value;
  }
  return out;
}

/**
 * A typed draft as the JSON value the server validates. A number field that is not a number goes through as text, so the server
 * answers with its own message for that field.
 * @param {{ type: string }} entry
 * @param {unknown} draft
 */
function coerce(entry, draft) {
  if (entry.type === 'bool') return draft === true;
  if (entry.type === 'int' || entry.type === 'float') {
    if (typeof draft === 'number') return draft;
    const text = String(draft ?? '').trim();
    if (text === '') return null;
    const n = Number(text);
    return Number.isFinite(n) && (entry.type === 'float' || Number.isInteger(n)) ? n : text;
  }
  return String(draft ?? '').trim();
}

/**
 * True when anything would be sent: edited values, or connection and stage changes (Task 18).
 * @param {Record<string, unknown>} values
 * @param {unknown} connections
 * @param {unknown} stages
 */
export function isDirty(values, connections, stages) {
  return Object.keys(values).length > 0 || connections != null || stages != null;
}

/** @param {boolean} dirty */
export function saveLabel(dirty) {
  return dirty ? 'Save Changes' : 'No Changes';
}

/** @param {{ ctrlKey?: boolean, metaKey?: boolean, key?: string }} e */
export function isSaveShortcut(e) {
  return Boolean((e.ctrlKey || e.metaKey) && String(e.key ?? '').toLowerCase() === 's');
}

/**
 * Per-field messages from a 400 `{errors: {KEY: message}}` body, ready to show under the named field. Connection errors come as
 * "connections.<name>.<field>" and stage errors as "stages.<stage>".
 * @param {{ errors?: unknown } | null | undefined} payload
 * @returns {Record<string, string>}
 */
export function fieldErrors(payload) {
  const errors = payload?.errors;
  if (errors === null || typeof errors !== 'object' || Array.isArray(errors)) return {};
  return Object.fromEntries(Object.entries(errors).filter(([, v]) => typeof v === 'string'));
}

/**
 * One sentence for a refused save that is not a field error.
 * @param {number} status
 * @param {{ error?: unknown } | null | undefined} payload
 */
export function describeSaveError(status, payload) {
  const detail = typeof payload?.error === 'string' ? payload.error.replace(/\.+$/, '') : '';
  if (status === 401) return 'Session expired. Sign in again.';
  if (status === 403)
    return detail ? `${detail[0].toUpperCase()}${detail.slice(1)}.` : 'Not allowed for your role.';
  if (status === 409)
    return 'These settings changed since you opened the page. The current values are shown; review and save again.';
  if (status === 503) return 'The settings are busy. Nothing was saved; try again in a moment.';
  if (status === 507) return 'The config volume is full. Nothing was saved.';
  if (status === 400) return 'Some values are not valid. See the fields marked in red.';
  return detail ? `${detail} (HTTP ${status}).` : `Could not save (HTTP ${status}).`;
}

// --- Row display --------------------------------------------------------------------------------------------------------------

const SOURCE_LABELS = { ui: 'Set here', env: 'From the container', default: 'Default' };

/**
 * One row's display model from its schema entry and its GET /api/settings info.
 * @param {any} entry
 * @param {any} info
 * @param {{ secretsWritable?: boolean } | null | undefined} ctx
 */
export function describeRow(entry, info, ctx) {
  const reason = readOnlyReason(entry, ctx);
  const source = info?.source ?? 'default';
  return {
    key: entry.key,
    label: entry.label,
    help: entry.help,
    type: entry.type,
    enum: entry.enum ?? [],
    secret: Boolean(entry.secret),
    restart: entry.applies === 'restart',
    value: info?.value,
    isSet: Boolean(info?.set),
    source,
    sourceLabel: SOURCE_LABELS[/** @type {keyof typeof SOURCE_LABELS} */ (source)] ?? source,
    overridesEnv: Boolean(info?.overridden_env),
    pending: Boolean(info?.pending),
    envInvalid: Boolean(info?.env_invalid),
    editable: reason === '',
    readOnlyReason: reason,
  };
}

/**
 * The text a read-only row shows. Secrets are only ever "Set" or "Not set".
 * @param {{ type: string, value?: unknown, isSet?: boolean }} row
 */
export function displayValue(row) {
  if (row.type === 'secret') return row.isSet ? 'Set' : 'Not set';
  if (typeof row.value === 'boolean') return row.value ? 'On' : 'Off';
  const text = row.value === null || row.value === undefined ? '' : String(row.value).trim();
  if (!text) return 'Not set';
  return text.length > 120 ? `${text.slice(0, 120)}…` : text;
}
