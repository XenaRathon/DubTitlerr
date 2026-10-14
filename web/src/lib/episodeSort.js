// Sort orders for the review inbox and the per-browser memory of the operator's choice.
// Pure, so node:test can import it without a browser.

/** Episode-list orders. `default` keeps the server's order (most repairs to check first). */
export const EPISODE_SORTS = /** @type {const} */ (['default', 'episode', 'pending', 'oldest']);
/** In-episode orders for the inbox; the shared view's `repeated` is not remembered. */
export const LINE_SORTS = /** @type {const} */ (['risk', 'time']);

const natural = (/** @type {string} */ a, /** @type {string} */ b) =>
  a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });

/**
 * @template {{ show: string, season: string, name: string, admitted: number, oldest_pending_at?: string | null }} T
 * @param {T} a
 * @param {T} b
 */
const byEpisode = (a, b) => natural(a.show, b.show) || natural(a.season, b.season) || natural(a.name, b.name);

/**
 * A sorted copy of the episodes. Unknown orders keep the input order.
 * @template {{ show: string, season: string, name: string, admitted: number, oldest_pending_at?: string | null }} T
 * @param {T[]} episodes
 * @param {string} order
 * @returns {T[]}
 */
export function sortEpisodes(episodes, order) {
  if (order === 'episode') return episodes.slice().sort(byEpisode);
  if (order === 'pending') return episodes.slice().sort((a, b) => b.admitted - a.admitted || byEpisode(a, b));
  // oldest_pending_at is the oldest undecided entry's own timestamp (the queue file's write time only when no entry
  // carries one), ISO 8601 UTC in one fixed format, so string order is time order. Episodes without one go last.
  if (order === 'oldest')
    return episodes.slice().sort((a, b) => {
      const x = a.oldest_pending_at ?? null;
      const y = b.oldest_pending_at ?? null;
      if (x !== y) {
        if (x === null) return 1;
        if (y === null) return -1;
        return x < y ? -1 : 1;
      }
      return byEpisode(a, b);
    });
  return episodes;
}

/**
 * The stored order when it is one of `allowed`, else `fallback`. Storage that is missing or throws counts as empty.
 * @template {string} T
 * @param {Pick<Storage, 'getItem'> | undefined} storage
 * @param {string} key
 * @param {readonly T[]} allowed
 * @param {T} fallback
 * @returns {T}
 */
export function readSortPref(storage, key, allowed, fallback) {
  try {
    const value = storage?.getItem(key);
    return allowed.find((v) => v === value) ?? fallback;
  } catch {
    return fallback;
  }
}

/**
 * Remember an order; storage that is missing or throws is ignored, so the choice holds for this page only.
 * @param {Pick<Storage, 'setItem'> | undefined} storage
 * @param {string} key
 * @param {string} value
 */
export function writeSortPref(storage, key, value) {
  try {
    storage?.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}
