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
  const settings = schema?.settings ?? [];
  return {
    rows: settings.filter(
      (s) => s.category === category && s.managed_by !== 'bootstrap' && (showAdvanced || !s.advanced),
    ),
    // Every bootstrap value lists under General, whatever category the registry gives it (the provider keys are 'connections').
    bootstrap: category === 'general' ? settings.filter((s) => s.managed_by === 'bootstrap') : [],
  };
}

/**
 * Why a row cannot be edited, or '' when it can. The wording of the first-wave rule is the spec's.
 * @param {any} entry
 * @param {{ secretsWritable?: boolean, canEdit?: boolean } | null | undefined} ctx
 * @returns {string}
 */
export function readOnlyReason(entry, ctx) {
  if (entry.managed_by === 'bootstrap') return 'Set in the container environment';
  if (entry.managed_by === 'connections') return 'Set through a Connection';
  if (entry.managed_by === 'retired') return 'Retired: no longer read';
  if (!entry.editable) return 'edit in a later release';
  if (ctx?.canEdit === false) return 'Only an admin can change settings';
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
  return Object.keys(values).length > 0 || (connections !== null && connections !== undefined) || (stages !== null && stages !== undefined);
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

// --- Restart (S-12) ---------------------------------------------------------------------------------------------------------

export const RESTART_TIMEOUT_MS = 10 * 60 * 1000;
export const RESTART_POLL_MS = 2000;

/**
 * The step the restart overlay is in. Only a boot_id different from the one seen before the restart ends it: the old server keeps
 * answering while the builder finishes the episode in flight, so "the server answers" proves nothing.
 * @param {{ oldBootId: string, startedAt: number, now: number, status?: { boot_id?: unknown } | null }} s
 * @returns {'waiting' | 'back' | 'timeout'}
 */
export function restartStep({ oldBootId, startedAt, now, status }) {
  const id = status?.boot_id;
  if (typeof id === 'string' && id !== '' && id !== oldBootId) return 'back';
  return now - startedAt >= RESTART_TIMEOUT_MS ? 'timeout' : 'waiting';
}

/**
 * The line under "restarting" in the overlay. A heartbeat stamped by a clock slightly ahead of the server's reads as 0 s, never
 * as a negative age.
 * @param {{ header?: { builder_heartbeat_age_s?: unknown } } | null | undefined} status
 */
export function describeRestartWait(status) {
  const age = status?.header?.builder_heartbeat_age_s;
  return typeof age === 'number'
    ? `Last builder heartbeat ${Math.max(0, Math.round(age))} s ago.`
    : 'Waiting for the builder to come back.';
}

// --- Row display --------------------------------------------------------------------------------------------------------------

const SOURCE_LABELS = { ui: 'Set here', env: 'From the container', default: 'Default' };

/**
 * One row's display model from its schema entry and its GET /api/settings info.
 * @param {any} entry
 * @param {any} info
 * @param {{ secretsWritable?: boolean, canEdit?: boolean } | null | undefined} ctx
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

// --- Connections (S-8) ------------------------------------------------------------------------------------------------------

/** @param {{ timeout_defaults?: { timeout_connect?: number, timeout_read?: number } } | null | undefined} rules */
export function blankConnection(rules) {
  const t = rules?.timeout_defaults ?? {};
  return {
    name: '',
    kind: 'llamacpp',
    url: '',
    model: '',
    extra_body: {},
    timeout_connect: t.timeout_connect ?? 10,
    timeout_read: t.timeout_read ?? 120,
    api_key: { set: false },
  };
}

/**
 * What a stage can pick: the connections of an accepted kind, plus "follow the decision stage" for verify.
 * @param {{ stages?: Array<{ id: string, kinds: string[] }>, via_decision?: string } | null | undefined} rules
 * @param {string} stage
 * @param {Array<{ name: string, kind: string }>} connections
 * @returns {Array<{ value: string, label: string }>}
 */
export function stageChoices(rules, stage, connections) {
  const kinds = rules?.stages?.find((s) => s.id === stage)?.kinds ?? [];
  const out = connections
    .filter((c) => c.name && kinds.includes(c.kind))
    .map((c) => ({ value: c.name, label: c.name }));
  if (stage === 'verify' && rules?.via_decision)
    out.push({ value: rules.via_decision, label: 'Follow the decision stage' });
  return out;
}

/**
 * The text of an "extra body" box as the JSON object the server stores. Empty is {}.
 * @param {string} text
 * @returns {{ value: Record<string, unknown> | null, error: string }}
 */
export function parseExtraBody(text) {
  const trimmed = String(text ?? '').trim();
  if (trimmed === '') return { value: {}, error: '' };
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { value: null, error: 'Must be a JSON object, like {"reasoning": {"effort": "low"}}.' };
    }
    return { value: parsed, error: '' };
  } catch {
    return { value: null, error: 'Not valid JSON.' };
  }
}

const CONNECTION_FIELDS = [
  'name',
  'kind',
  'url',
  'model',
  'model_secondary',
  'extra_body',
  'timeout_connect',
  'timeout_read',
];

/**
 * The PUT `connections` list from the working copies. Each carries its stored fields; `key` (typed text, CLEAR, or absent) becomes
 * api_key only when the operator touched it, so an untouched connection keeps the key the server holds. The extra body is
 * write-only too: GET reports it as {set: bool} and that marker goes back as it came, which tells the server to keep the stored
 * body; a replaced body is the new object. Only OpenAI-compatible connections carry one.
 * @param {Array<any>} working
 */
export function connectionsBody(working) {
  return working.map((c) => {
    /** @type {Record<string, unknown>} */
    const item = Object.fromEntries(
      CONNECTION_FIELDS.filter((f) => c[f] !== undefined).map((f) => [f, c[f]]),
    );
    if (c.kind !== 'openai') item.extra_body = {};
    if (c.key === CLEAR) item.api_key = { clear: true };
    else if (typeof c.key === 'string' && c.key !== '') item.api_key = c.key;
    return item;
  });
}

/**
 * True when the working copies differ from the loaded connections, or any key was touched.
 * @param {Array<any>} loaded
 * @param {Array<any>} working
 */
export function connectionsChanged(loaded, working) {
  if (working.some((c) => c.key === CLEAR || (typeof c.key === 'string' && c.key !== ''))) return true;
  const strip = (/** @type {any[]} */ list) =>
    JSON.stringify(list.map((c) => Object.fromEntries(CONNECTION_FIELDS.map((f) => [f, c[f]]))));
  return strip(loaded) !== strip(working);
}

/**
 * The stage picks that differ from the loaded ones, as the PUT `stages` object (null removes a pick), or null for no change.
 * @param {Record<string, string> | undefined} loaded
 * @param {Record<string, string> | undefined} picks
 */
export function stagesBody(loaded, picks) {
  /** @type {Record<string, string | null>} */
  const out = {};
  for (const stage of new Set([...Object.keys(loaded ?? {}), ...Object.keys(picks ?? {})])) {
    const before = loaded?.[stage] ?? '';
    const after = picks?.[stage] ?? '';
    if (before !== after) out[stage] = after === '' ? null : after;
  }
  return Object.keys(out).length ? out : null;
}

/**
 * One plain sentence for a backend connectivity test. A carried HTTP status is mapped, never shown raw.
 * @param {{ ok?: unknown, latency_ms?: unknown, error?: unknown, status?: unknown } | null | undefined} result
 * @returns {string}
 */
export function describeTestResult(result) {
  if (result?.ok === true) {
    const ms = typeof result.latency_ms === 'number' ? result.latency_ms : 0;
    return `Connection ok in ${ms} ms.`;
  }
  const err =
    typeof result?.error === 'string' && result.error.trim() !== ''
      ? result.error.trim()
      : 'Connection failed.';
  if (typeof result?.status === 'number') {
    if (result.status === 429) return 'Too many checks. Wait a moment and retry.';
    if (result.status >= 500) return `The test failed (HTTP ${result.status}): ${err}`;
    return `${err} (HTTP ${result.status}).`;
  }
  return err;
}
