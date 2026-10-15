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
