/** Pure helpers for the glossary editor page (specs/webui-glossary-editor, Data contracts). */

/** @typedef {'names' | 'phrases' | 'hard_fixes'} GlossaryKey */
/** @typedef {'add' | 'update' | 'delete'} GlossaryOp */
/** @typedef {string | [string, string]} GlossaryRow */

// Mirrors review_glossary.py: control, format (zero-width, bidi), surrogate, private-use and line/paragraph separators.
const BAD_CHARS = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/u;
const VALID_KEYS = ['names', 'phrases', 'hard_fixes'];

/**
 * Rows whose term (or, for pairs, either side) contains the query, case-insensitively.
 * An empty query returns a copy of the whole list.
 * @param {GlossaryRow[]} list
 * @param {string} query
 * @returns {GlossaryRow[]}
 */
export function filterTerms(list, query) {
  const q = String(query ?? '')
    .trim()
    .toLowerCase();
  if (!q) return list.slice();
  return list.filter((item) => {
    if (Array.isArray(item))
      return String(item[0]).toLowerCase().includes(q) || String(item[1]).toLowerCase().includes(q);
    return String(item).toLowerCase().includes(q); // a hand-edited file can hold numbers or nulls
  });
}

/**
 * A new array sorted by term, case-insensitively; the input is never mutated.
 * @param {GlossaryRow[]} list
 * @returns {GlossaryRow[]}
 */
export function sortTerms(list) {
  return list.slice().sort((a, b) => {
    const ka = String(Array.isArray(a) ? a[0] : a);
    const kb = String(Array.isArray(b) ? b[0] : b);
    return ka.localeCompare(kb, undefined, { sensitivity: 'base' });
  });
}

/**
 * Mirror of the server validation limits; null when the term is usable.
 * `value` of null/undefined means add (names/phrases) or delete and is not checked.
 * @param {string} key
 * @param {unknown} term
 * @param {unknown} value
 * @returns {string | null}
 */
export function validateTerm(key, term, value) {
  if (!VALID_KEYS.includes(key)) return 'Unknown glossary section.';
  if (typeof term !== 'string') return 'Term must be text.';
  // Trim then NFC, like the server: length is counted on the composed form.
  const t = term.trim().normalize('NFC');
  if (!t) return 'Term must not be empty.';
  if (BAD_CHARS.test(t)) return 'Term must not contain control or invisible characters.';
  // Names and phrases are matched as text; a backslash only makes sense in a hard-fix replacement.
  if (key !== 'hard_fixes' && t.includes('\\')) return 'Term must not contain a backslash.';
  const max = key === 'names' ? 80 : 120;
  if (t.length > max) return `Term must be ${max} characters or fewer.`;
  if (key === 'phrases' && !t.includes(' ')) return 'Phrases need a space; single tokens belong in names.';
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') return 'Value must be text.';
  const v = value.trim().normalize('NFC');
  if (!v) return 'Value must not be empty.';
  if (BAD_CHARS.test(v)) return 'Value must not contain control or invisible characters.';
  if (key !== 'hard_fixes' && v.includes('\\')) return 'Value must not contain a backslash.';
  if (v.length > max) return `Value must be ${max} characters or fewer.`;
  if (key === 'phrases' && !v.includes(' ')) return 'Phrases need a space; single tokens belong in names.';
  if (key === 'hard_fixes' && v.toLowerCase() === t.toLowerCase())
    return 'Hard-fix key and value must differ.';
  return null;
}

/**
 * Whether the add form or the open edit row holds changes that are not saved yet.
 * @param {{ newTerm: string, newValue: string, editTerm: string | null, editDraft: string, editValue: string, saved: Record<string, string> }} s
 * @returns {boolean}
 */
export function isDirty(s) {
  if (s.newTerm.trim() !== '' || s.newValue.trim() !== '') return true;
  if (s.editTerm === null) return false;
  return s.editDraft !== s.editTerm || s.editValue !== (s.saved[s.editTerm] ?? '');
}

/**
 * The POST /api/glossary body. Delete ignores any value passed.
 * @param {string} show
 * @param {GlossaryOp} op
 * @param {GlossaryKey} key
 * @param {string} term
 * @param {string | null} value
 * @param {string} expected_version
 * @returns {{ show: string, op: GlossaryOp, key: GlossaryKey, term: string, value: string | null, expected_version: string }}
 */
export function buildOp(show, op, key, term, value, expected_version) {
  return { show, op, key, term, value: op === 'delete' ? null : (value ?? null), expected_version };
}

/**
 * One plain sentence for a glossary error response.
 * @param {number} status
 * @param {{ error?: unknown, version?: unknown } | null | undefined} payload
 * @returns {string}
 */
export function describeError(status, payload) {
  const raw = typeof payload?.error === 'string' ? payload.error.trim() : '';
  const detail = raw.replace(/\.+$/, '');
  if (status === 503) return 'glossary busy, try again';
  if (status === 409) return 'Version conflict — reloaded the latest version. Review and try again.';
  if (status === 404) return detail ? `Unknown show: ${detail}.` : 'Unknown show: no such glossary.';
  if (status === 400)
    return detail ? `Invalid request: ${detail}.` : 'Invalid request. Check the term and try again.';
  return detail ? `${detail}.` : `Request failed (${status}).`;
}
