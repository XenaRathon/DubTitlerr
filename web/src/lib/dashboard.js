/** Pure helpers for the status dashboard page (specs/webui-status-dashboard, Data contracts). */

/** @typedef {'transcribed' | 'repaired' | 'muxed' | 'failed' | 'stale' | 'pending-review'} EpisodeStage */
/** @typedef {'info' | 'ok' | 'warn' | 'bad' | 'muted'} StatusToken */

const STAGE_TOKENS = {
  transcribed: 'info',
  repaired: 'info',
  muxed: 'ok',
  failed: 'bad',
  stale: 'warn',
  'pending-review': 'warn',
};
const STAGE_ORDER = ['transcribed', 'repaired', 'muxed', 'failed', 'stale', 'pending-review'];

/**
 * The status token for a pipeline stage; unknown stages share one muted token
 * so the badge text (never colour alone) carries the meaning.
 * @param {string} stage
 * @returns {StatusToken}
 */
export function stageClass(stage) {
  const known = /** @type {Partial<Record<string, StatusToken>>} */ (STAGE_TOKENS)[stage];
  return known ?? 'muted';
}

/**
 * A heartbeat/cache age in seconds as "14 s", "3 min" or "2 h"; anything missing as "unknown".
 * @param {unknown} seconds
 * @returns {string}
 */
export function formatAge(seconds) {
  const s = typeof seconds === 'number' ? seconds : NaN;
  if (!Number.isFinite(s) || s < 0) return 'unknown';
  if (s < 60) return `${Math.floor(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h`;
}

/**
 * Per-stage counts from a /api/status header in canonical stage order; missing stages count zero.
 * The server counts the returned page only (counts_scope: "page").
 * @param {{ counts_per_stage?: unknown } | null | undefined} header
 * @returns {Array<{ stage: string, count: number }>}
 */
export function summarizeCounts(header) {
  const raw =
    typeof header?.counts_per_stage === 'object' && header?.counts_per_stage !== null
      ? header.counts_per_stage
      : {};
  const counts = /** @type {Record<string, unknown>} */ (raw);
  return STAGE_ORDER.map((stage) => {
    const n = counts[stage];
    return { stage, count: typeof n === 'number' && Number.isFinite(n) ? n : 0 };
  });
}

/**
 * Up to five page numbers around the current page for the pagination control.
 * @param {number} page
 * @param {number} pages
 * @returns {number[]}
 */
export function pageWindow(page, pages) {
  const total = Math.max(1, Math.floor(pages) || 1);
  const current = Math.min(Math.max(1, Math.floor(page) || 1), total);
  const end = Math.min(total, Math.max(1, Math.min(current - 2, total - 4)) + 4);
  const start = Math.max(1, end - 4);
  const out = [];
  for (let p = start; p <= end; p++) out.push(p);
  return out;
}

/**
 * The GET /api/status query string. Page defaults to 1, limit to 50 and is capped at 200.
 * @param {{ show?: unknown, page?: unknown, limit?: unknown }} opts
 * @returns {string}
 */
export function buildQuery(opts) {
  const show = typeof opts.show === 'string' ? opts.show.trim() : '';
  const page =
    typeof opts.page === 'number' && Number.isFinite(opts.page) ? Math.max(1, Math.floor(opts.page)) : 1;
  const limit =
    typeof opts.limit === 'number' && Number.isFinite(opts.limit)
      ? Math.min(200, Math.max(1, Math.floor(opts.limit)))
      : 50;
  const parts = [];
  if (show) parts.push(`show=${encodeURIComponent(show)}`);
  parts.push(`page=${page}`, `limit=${limit}`);
  return `?${parts.join('&')}`;
}

export const MAX_WARMING_RETRIES = 5;
const WARMING_RETRY_MS = 5000;

/**
 * Milliseconds to wait before the next retry while the server's index is warming, or null once the
 * retries are used up (or the attempt number is not a usable count).
 * @param {number} attempt retries already made, starting at 0
 * @returns {number | null}
 */
export function warmingRetryDelay(attempt) {
  if (!Number.isInteger(attempt) || attempt < 0 || attempt >= MAX_WARMING_RETRIES) return null;
  return WARMING_RETRY_MS;
}

/**
 * Sequence token for overlapping fetches: only the request started last may apply its result.
 * @returns {{ begin: () => number, isCurrent: (id: number) => boolean, cancel: () => void }}
 */
export function createLatest() {
  let current = 0;
  return {
    begin: () => ++current,
    isCurrent: (id) => id === current,
    // Teardown: nothing in flight may apply afterwards.
    cancel: () => {
      current++;
    },
  };
}
