/** Pure helpers for the read-only settings page (specs/webui-settings, Data contracts). */

/** @type {Array<[string, Array<string>]>} */
const GROUPS = [
  [
    'Repair',
    ['repair_backend', 'repair_model', 'repair_llamacpp_url', 'repair_openai_url', 'repair_unanchored'],
  ],
  ['Verify', ['verify_backend', 'verify_decision_model']],
  ['Acquire', ['acquire_backend', 'acquire_apply', 'glossary_arc_tags']],
  ['Transcription', ['whisper_model', 'compute_type', 'require_eng']],
  ['Schedule & loop', ['rescan_interval', 'merge_window']],
  ['Paths', ['merge_roots', 'anime_order']],
];
const FLAG_KEYS = ['require_eng', 'repair_unanchored', 'acquire_apply'];

/**
 * File the settings into their display sections; empty sections are dropped and
 * keys outside every section land in a trailing Other group.
 * @param {Record<string, unknown> | null | undefined} settings
 * @returns {Array<{ title: string, entries: Array<{ key: string, value: unknown }> }>}
 */
export function groupSettings(settings) {
  const src = settings ?? {};
  const seen = new Set();
  const groups = [];
  for (const [title, keys] of GROUPS) {
    const entries = [];
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(src, key)) {
        entries.push({ key, value: src[key] });
        seen.add(key);
      }
    }
    if (entries.length > 0) groups.push({ title, entries });
  }
  const rest = Object.keys(src)
    .filter((key) => !seen.has(key))
    .map((key) => ({ key, value: src[key] }));
  if (rest.length > 0) groups.push({ title: 'Other', entries: rest });
  return groups;
}

/**
 * One display string for a setting value: empty means not set, booleans read
 * yes/no, long colon/comma lists show the first three with a remainder count.
 * @param {string} key
 * @param {unknown} value
 * @returns {string}
 */
export function formatValue(key, value) {
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  const text = value === null || value === undefined ? '' : String(value).trim();
  // Unset acquire_apply means apply (gen_loop.sh), so it never reads "not set".
  if (!text && key === 'acquire_apply') return 'yes (default)';
  if (!text) return 'not set';
  if (FLAG_KEYS.includes(key)) {
    if (key === 'acquire_apply') return /^(0|false|no|off|dry-run)$/i.test(text) ? 'no' : 'yes';
    if (/^(1|true|yes|on)$/i.test(text)) return 'yes';
    if (/^(0|false|no|off)$/i.test(text)) return 'no';
  }
  // Only path-list settings split on separators; URLs and IPv6 hosts stay whole.
  if (['merge_roots', 'anime_order'].includes(key)) {
    const parts = text
      .split(/[:,]/)
      .map((part) => part.trim())
      .filter((part) => part !== '');
    if (parts.length > 3) return `${parts.slice(0, 3).join(', ')}… (+${parts.length - 3} more)`;
  }
  if (text.length > 80) return `${text.slice(0, 80)}…`;
  return text;
}

/**
 * Secrets as set/not-set badges, sorted by name. Values never leave this function.
 * @param {Record<string, unknown> | null | undefined} secrets
 * @returns {Array<{ name: string, set: boolean }>}
 */
export function secretBadges(secrets) {
  const src = secrets ?? {};
  return Object.keys(src)
    .sort()
    .map((name) => ({ name, set: Boolean(src[name]) }));
}

/**
 * One plain sentence for a backend connectivity test. A carried HTTP status is
 * mapped, never shown raw; the review wrapper's 401 text maps to a re-sign-in plea.
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
  if (/access token not accepted/i.test(err)) return 'Session expired. Sign in again and retry.';
  if (typeof result?.status === 'number') {
    if (result.status === 429) return 'Too many checks. Wait a moment and retry.';
    if (result.status >= 500) return `Settings tester failed (HTTP ${result.status}): ${err}`;
    return `${err} (HTTP ${result.status}).`;
  }
  return err;
}

/**
 * One sentence saying where the reported values came from.
 * @param {unknown} source
 * @returns {string}
 */
export function sourceNote(source) {
  if (source === 'effective.env') return 'Values reported by the builder at sweep start.';
  return "Values from this container's own environment, which may differ from the builder.";
}

const MODEL_RE = /^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/;
const WRITABLE_KEYS = [
  'repair_profile',
  'repair_model',
  'verify_backend',
  'verify_decision_model',
  'require_eng',
  'acquire_apply',
];

/**
 * Null when the model id matches the server shape, else a plain sentence.
 * @param {unknown} value
 * @returns {string | null}
 */
export function validateModel(value) {
  if (typeof value !== 'string' || !MODEL_RE.test(value.trim())) {
    return 'Model must look like qwen3-4b-instruct: letters, digits, . _ : / - up to 128 chars.';
  }
  return null;
}

/**
 * The PUT /api/settings body: only fields that differ from the loaded settings.
 * A cleared text field sends null; requireEng (boolean) compares against the
 * loaded flag and sends 1/0. Empty string means "no value set".
 * @param {Record<string, unknown> | null | undefined} current
 * acquire_apply is sent only when the toggle (acquireApply, boolean) differs from the server's effective
 * value (`acquire`, GET's acquire_apply): unset means apply, so comparing with the raw string would write off.
 * @param {{ repair_profile?: unknown, repair_model?: unknown, verify_backend?: unknown, verify_decision_model?: unknown, requireEng?: unknown, acquireApply?: unknown }} edited
 * @param {{ enabled?: unknown } | null | undefined} [acquire]
 * @returns {Record<string, string | number | boolean | null>}
 */
export function buildSettingsBody(current, edited, acquire) {
  const src = current ?? {};
  /** @type {Record<string, string | number | boolean | null>} */
  const body = {};
  const flag = (/** @type {unknown} */ v) =>
    v === true ||
    v === 1 ||
    String(v ?? '')
      .trim()
      .toLowerCase() === '1'
      ? true
      : false;
  const editBag = /** @type {Record<string, unknown>} */ (edited);
  for (const key of WRITABLE_KEYS) {
    if (key === 'acquire_apply') {
      if (typeof acquire?.enabled === 'boolean' && typeof edited.acquireApply === 'boolean') {
        if (edited.acquireApply !== acquire.enabled) body[key] = edited.acquireApply;
      }
      continue;
    }
    if (key === 'require_eng') {
      if (flag(edited.requireEng) !== flag(src[key])) body[key] = edited.requireEng === true ? 1 : 0;
      continue;
    }
    const next = typeof editBag[key] === 'string' ? editBag[key].trim() : '';
    const prev = typeof src[key] === 'string' ? src[key].trim() : String(src[key] ?? '').trim();
    if (next !== prev) body[key] = next === '' ? null : next;
  }
  return body;
}

const ACQUIRE_SOURCES = { runtime: 'runtime file', env: 'environment', default: 'default' };

/**
 * One plain sentence for the acquire-apply toggle: the effective value, where it came from, when a change lands.
 * @param {{ enabled?: unknown, source?: unknown } | null | undefined} state
 * @returns {string}
 */
export function describeAcquireApply(state) {
  if (typeof state?.enabled !== 'boolean') return 'Current value unknown.';
  const from = ACQUIRE_SOURCES[/** @type {keyof typeof ACQUIRE_SOURCES} */ (state.source)] ?? 'unknown source';
  return `Currently ${state.enabled ? 'on' : 'off'} (from the ${from}). A change takes effect at the next sweep.`;
}

/**
 * The pending acquire-apply badge reads the meaning: unset (null) means apply, so only an explicit false is "off".
 * @param {unknown} value
 * @returns {string}
 */
export function describePendingAcquireApply(value) {
  return value === false ? 'off' : 'on';
}

/**
 * One plain sentence for a settings-write error. The two admin-token problems
 * read differently; validation and server text pass through with their status.
 * @param {number} status
 * @param {{ error?: unknown } | null | undefined} payload
 * @returns {string}
 */
export function describeWriteError(status, payload) {
  const raw = typeof payload?.error === 'string' ? payload.error.trim() : '';
  const detail = raw.replace(/\.+$/, '');
  if (status === 401) return 'Session expired. Sign in again.';
  if (status === 403) {
    if (detail === 'admin writes are disabled')
      return 'Admin writes are disabled: set REVIEW_ADMIN_TOKEN on the server.';
    if (detail === 'admin token required') return 'Admin token required: enter it below and retry.';
    return 'Not allowed. Check the admin token and retry.';
  }
  if (status === 400) {
    // An allow-list refusal ("verify backend not allowed: the operator lists … in RUNTIME_…") names what to change.
    const refused = /^(.+?) not allowed: (.+)$/.exec(detail);
    if (refused)
      return `Not allowed on this server: ${refused[1]}. ${refused[2][0].toUpperCase()}${refused[2].slice(1)}.`;
    return detail ? `Invalid request: ${detail}.` : 'Invalid request. Check the form.';
  }
  return detail ? `${detail} (HTTP ${status}).` : `Request failed (${status}).`;
}

/**
 * Pending runtime.env overrides as sorted {key, value} pairs; anything else is [].
 * @param {unknown} pending
 * @returns {Array<{ key: string, value: unknown }>}
 */
export function pendingEntries(pending) {
  if (pending === null || pending === undefined || typeof pending !== 'object' || Array.isArray(pending)) {
    return [];
  }
  return Object.keys(/** @type {Record<string, unknown>} */ (pending))
    .sort()
    .map((key) => ({ key, value: /** @type {Record<string, unknown>} */ (pending)[key] }));
}

/**
 * The options for a select the server limits (allowed_verify_backends, allowed_decision_models): the server list,
 * trimmed and deduplicated. A current value outside the list stays visible as a disabled option, so the select
 * never shows the wrong value and a save of another field cannot silently reset it.
 * @param {unknown} allowed
 * @param {string} current
 * @returns {Array<{ value: string, label: string, disabled: boolean }>}
 */
export function allowedChoices(allowed, current) {
  const list = Array.isArray(allowed)
    ? [...new Set(allowed.filter((v) => typeof v === 'string').map((v) => v.trim()))].filter(Boolean)
    : [];
  const out = list.map((value) => ({ value, label: value, disabled: false }));
  const now = (current ?? '').trim();
  if (now && !list.includes(now))
    out.push({ value: now, label: `${now} (current, not allowed on this server)`, disabled: true });
  return out;
}
