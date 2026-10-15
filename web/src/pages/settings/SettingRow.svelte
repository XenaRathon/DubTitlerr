<script lang="ts">
  import { displayValue } from '../../lib/settingsModel.js';

  type Row = ReturnType<typeof import('../../lib/settingsModel.js').describeRow>;
  let { row }: { row: Row } = $props();
  const id = $derived(`setting-${row.key}`);
</script>

<div class="setting-row" data-key={row.key}>
  <div class="setting-head">
    <p class="setting-label">{row.label}</p>
    {#if row.restart}<span class="badge" data-tone="warn">Restart required</span>{/if}
    <span class="badge" data-tone="muted">{row.sourceLabel}</span>
    {#if row.overridesEnv}<span class="badge" data-tone="info">Overrides the container value</span>{/if}
    {#if row.pending}<span class="badge" data-tone="warn">Pending</span>{/if}
  </div>
  <p class="setting-value" {id}>{displayValue(row)}</p>
  {#if row.readOnlyReason}<p class="setting-reason">{row.readOnlyReason}</p>{/if}
  {#if row.envInvalid}<p class="setting-reason">The container value is not valid for this setting.</p>{/if}
  <p class="setting-help">{row.help}</p>
</div>

<style>
  .setting-row {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    display: grid;
    gap: 4px;
  }
  .setting-head {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .setting-label {
    margin: 0;
    font-weight: 600;
  }
  .setting-value {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .setting-reason,
  .setting-help {
    margin: 0;
    color: var(--muted);
  }
</style>
