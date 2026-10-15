<script lang="ts">
  import { RESET, displayValue } from '../../lib/settingsModel.js';

  type Row = ReturnType<typeof import('../../lib/settingsModel.js').describeRow>;
  let {
    row,
    draft,
    error = '',
    onchange,
    onreset,
  }: {
    row: Row;
    /** What the operator typed or chose, or undefined when the row is untouched. */
    draft?: unknown;
    /** The server's message for this field after a refused save. */
    error?: string;
    onchange?: (value: unknown) => void;
    onreset?: () => void;
  } = $props();

  const id = $derived(`setting-${row.key}`);
  const editing = $derived(row.editable && !row.secret);
  const resetting = $derived(draft === RESET);
  const shown = $derived(draft === undefined || draft === RESET ? row.value : draft);
  const text = $derived(shown === null || shown === undefined ? '' : String(shown));
  const numeric = $derived(row.type === 'int' || row.type === 'float');
</script>

<div class="setting-row" data-key={row.key}>
  <div class="setting-head">
    {#if editing}
      <label class="setting-label" for={id}>{row.label}</label>
    {:else}
      <p class="setting-label">{row.label}</p>
    {/if}
    {#if row.restart}<span class="badge" data-tone="warn">Restart required</span>{/if}
    <span class="badge" data-tone="muted">{row.sourceLabel}</span>
    {#if row.overridesEnv}<span class="badge" data-tone="info">Overrides the container value</span>{/if}
    {#if row.pending}<span class="badge" data-tone="warn">Pending</span>{/if}
  </div>
  {#if !editing}
    <p class="setting-value" {id}>{displayValue(row)}</p>
    {#if row.readOnlyReason}<p class="setting-reason">{row.readOnlyReason}</p>{/if}
  {:else}
    <div class="setting-control">
      {#if row.type === 'bool'}
        <input
          {id}
          type="checkbox"
          checked={shown === true}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onchange={(e) => onchange?.(e.currentTarget.checked)}
        />
      {:else if row.type === 'enum'}
        <select
          {id}
          value={text}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onchange={(e) => onchange?.(e.currentTarget.value)}
        >
          {#each row.enum as option (option)}<option value={option}>{option}</option>{/each}
        </select>
      {:else}
        <input
          {id}
          type="text"
          inputmode={numeric ? 'decimal' : undefined}
          autocomplete="off"
          spellcheck="false"
          value={text}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          oninput={(e) => onchange?.(e.currentTarget.value)}
        />
      {/if}
      {#if row.source === 'ui' && !resetting}
        <button class="secondary" type="button" aria-label={`Reset ${row.label}`} onclick={() => onreset?.()}
          >Reset</button
        >
      {/if}
      {#if resetting}<span class="setting-reason"
          >Goes back to the container value or the default when you save.</span
        >{/if}
    </div>
    {#if row.envInvalid}<p class="setting-reason">The container value is not valid for this setting.</p>{/if}
  {/if}
  <p class="setting-help">{row.help}</p>
  {#if error}<p class="field-error" id={`${id}-error`} role="alert">{error}</p>{/if}
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
  .setting-control {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .setting-control input[type='text'],
  .setting-control select {
    flex: 1 1 14rem;
    min-width: 0;
    max-width: 28rem;
  }
  .setting-reason,
  .setting-help {
    margin: 0;
    color: var(--muted);
  }
  .field-error {
    margin: 0;
    color: var(--bad);
  }
</style>
