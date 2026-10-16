/** Pure helpers for the run-requests page (specs/webui-run-control, Data contracts). */

/** @typedef {'info' | 'ok' | 'warn' | 'bad' | 'muted'} StatusToken */

const STATUS_TOKENS = {
  pending: 'info',
  running: 'info',
  done: 'ok',
  failed: 'bad',
};

/**
 * The status token for a request status; unknown statuses share one muted token
 * so the badge text (never colour alone) carries the meaning.
 * @param {string} status
 * @returns {StatusToken}
 */
export function statusClass(status) {
  const known = /** @type {Partial<Record<string, StatusToken>>} */ (STATUS_TOKENS)[status];
  return known ?? 'muted';
}

/**
 * The POST /api/requests body: trimmed, with blank optionals omitted.
 * A checked require-English box sends 1; anything else leaves the key out.
 * @param {{ show?: unknown, season?: unknown, episodeRe?: unknown, requireEng?: unknown }} form
 * @returns {{ show: string, season?: number, episode_re?: string, require_eng?: number }}
 */
export function buildRequestBody(form) {
  /** @type {{ show: string, season?: number, episode_re?: string, require_eng?: number }} */
  const body = { show: String(form.show ?? '').trim() };
  const seasonText = String(form.season ?? '').trim();
  if (seasonText !== '') {
    const season = Number.parseInt(seasonText, 10);
    if (!Number.isNaN(season)) body.season = season;
  }
  const reText = String(form.episodeRe ?? '').trim();
  if (reText !== '') body.episode_re = reText;
  if (form.requireEng === true) body.require_eng = 1;
  return body;
}

/**
 * When the show list loaded, the show must be one of it; with no list (empty or failed to load) any name is allowed and
 * the server decides.
 * @param {string} show
 * @param {string[]} shows
 * @returns {string | null}
 */
export function checkShowPick(show, shows) {
  if (!shows.length || shows.includes(show.trim())) return null;
  return 'Pick a show from the list.';
}

/**
 * Mirror of the server limits; null when the form may be queued.
 * @param {{ show?: unknown, season?: unknown, episodeRe?: unknown }} form
 * @returns {string | null}
 */
export function validateForm(form) {
  const show = typeof form.show === 'string' ? form.show.trim() : '';
  if (!show) return 'Show must not be empty.';
  if (
    show.includes('/') ||
    show.includes('\\') ||
    show.includes('..') ||
    show.includes('=') ||
    /[\r\n\u0000]/.test(show)
  ) {
    return 'Show must be a plain directory name.';
  }
  const season = typeof form.season === 'string' ? form.season.trim() : '';
  if (season !== '' && !/^[1-9]\d*$/.test(season)) return 'Season must be a positive integer.';
  const episodeRe = typeof form.episodeRe === 'string' ? form.episodeRe.trim() : '';
  if (episodeRe.length > 200) return 'Episode filter must be 200 characters or fewer.';
  if (episodeRe !== '') {
    try {
      new RegExp(episodeRe);
    } catch {
      return 'Episode filter is not a valid pattern.';
    }
  }
  return null;
}

/**
 * One plain sentence for a run-request error, keeping status and body apart so
 * an admin-only refusal reads differently from a rejected cross-site request and a 409 names its request.
 * @param {number} status
 * @param {{ error?: unknown, existing_id?: unknown } | null | undefined} payload
 * @returns {string}
 */
export function describeError(status, payload) {
  const raw = typeof payload?.error === 'string' ? payload.error.trim() : '';
  const detail = raw.replace(/\.+$/, '');
  if (status === 409) {
    const id = payload && typeof payload.existing_id === 'string' ? payload.existing_id : '';
    return id ? `Already queued as ${id}.` : 'Already queued.';
  }
  if (status === 401) return 'Session expired. Sign in again.';
  if (status === 403) return detail === 'admin only' ? 'Only administrators can do this.' : 'Not allowed.';
  if (status === 400) return detail ? `Invalid request: ${detail}.` : 'Invalid request. Check the form.';
  return detail ? `${detail} (HTTP ${status}).` : `Request failed (${status}).`;
}

/**
 * The short request id for the table: the hex suffix after the last dash.
 * @param {unknown} id
 * @returns {string}
 */
export function shortId(id) {
  if (typeof id !== 'string' || id === '') return '';
  const cut = id.lastIndexOf('-');
  if (cut >= 0 && cut < id.length - 1) return id.slice(cut + 1);
  return id.slice(0, 8);
}

/**
 * An ISO timestamp as local date and time; anything missing or unreadable as "—".
 * @param {unknown} iso
 * @returns {string}
 */
export function formatWhen(iso) {
  if (typeof iso !== 'string' || iso === '') return '—';
  const stamp = new Date(iso).getTime();
  if (Number.isNaN(stamp)) return '—';
  return new Date(iso).toLocaleString();
}

const TIME_RE = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const COMMON_ZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'Asia/Tokyo',
  'Australia/Sydney',
];

/**
 * Mirror of the server schedule limits; null when the window may be saved.
 * @param {{ enabled?: unknown, open?: unknown, close?: unknown, tz?: unknown }} form
 * @returns {string | null}
 */
export function validateSchedule(form) {
  if (typeof form.enabled !== 'boolean') return 'Enabled must be a switch.';
  for (const side of /** @type {Array<'open' | 'close'>} */ (['open', 'close'])) {
    const text = typeof form[side] === 'string' ? form[side].trim() : '';
    if (!TIME_RE.test(text)) return `${side === 'open' ? 'Open' : 'Close'} must be HH:MM (00:00 to 23:59).`;
  }
  const tz = typeof form.tz === 'string' ? form.tz.trim() : '';
  if (!tz) return 'Timezone must not be empty.';
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: tz });
  } catch {
    return `Unknown timezone: ${tz}.`;
  }
  return null;
}

/**
 * True when the window runs past midnight (open later than close).
 * @param {unknown} open
 * @param {unknown} close
 * @returns {boolean}
 */
export function crossesMidnight(open, close) {
  if (typeof open !== 'string' || typeof close !== 'string') return false;
  if (!TIME_RE.test(open) || !TIME_RE.test(close)) return false;
  return open > close;
}

/**
 * One plain sentence previewing what the window does.
 * @param {{ enabled?: unknown, open?: unknown, close?: unknown, tz?: unknown } | null | undefined} schedule
 * @returns {string}
 */
export function describeSchedule(schedule) {
  const open = typeof schedule?.open === 'string' ? schedule.open : '';
  const close = typeof schedule?.close === 'string' ? schedule.close : '';
  const tz = typeof schedule?.tz === 'string' ? schedule.tz : '';
  if (schedule?.enabled !== true) return 'Schedule window off; requests run whenever the loop reaches them.';
  let out = `Runs only between ${open} and ${close} ${tz}; requests wait outside that window.`;
  if (crossesMidnight(open, close)) out += ' Window crosses midnight.';
  return out;
}

/**
 * The PUT /api/schedule body: trimmed, with the switch kept a boolean.
 * @param {{ enabled?: unknown, open?: unknown, close?: unknown, tz?: unknown }} form
 * @returns {{ enabled: boolean, open: string, close: string, tz: string }}
 */
export function scheduleBody(form) {
  return {
    enabled: form.enabled === true,
    open: String(form.open ?? '').trim(),
    close: String(form.close ?? '').trim(),
    tz: String(form.tz ?? '').trim(),
  };
}

/**
 * A few common IANA zones for the timezone datalist.
 * @returns {string[]}
 */
export function commonZones() {
  return COMMON_ZONES.slice();
}
