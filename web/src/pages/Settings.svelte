<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { ApiError } from '../lib/api.js';
  import { SETTINGS_CATEGORIES, settingsHash } from '../lib/route.js';
  import {
    RESET,
    RESTART_POLL_MS,
    buildValues,
    categoryRows,
    describeRestartWait,
    describeRow,
    describeSaveError,
    fieldErrors,
    isDirty,
    loadShowAdvanced,
    restartStep,
    saveLabel,
    saveShowAdvanced,
  } from '../lib/settingsModel.js';
  import RestartDialog from './settings/RestartDialog.svelte';
  import RestartOverlay from './settings/RestartOverlay.svelte';
  import { isAdmin } from '../lib/roles.js';
  import SettingRow from './settings/SettingRow.svelte';
  import Security from './Security.svelte';
  import Accounts from './Accounts.svelte';

  let {
    api,
    category = '',
    role = 'user',
    dirty = $bindable(false),
  }: {
    api: (
      path: string,
      options?: { method?: string; body?: object; headers?: Record<string, string> },
    ) => Promise<any>;
    /** The category page to show; '' is the card grid. */
    category?: string;
    /** The signed-in role (login plan). An admin sees the account tools on the General page. */
    role?: string;
    /** True while the page holds edits the server has not saved. App reads it to guard navigation. */
    dirty?: boolean;
  } = $props();

  let schema = $state<any>(null);
  let loaded = $state<any>(null);
  let loading = $state(false);
  let loadError = $state('');
  let loadSeq = 0;
  let statusMsg = $state('');
  // key -> what the operator typed or chose (RESET to drop the stored value); only differences from the loaded page are sent.
  let drafts = $state<Record<string, unknown>>({});
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let saveError = $state('');
  let saveMessage = $state('');
  // Restart (S-12): the dialog lists the saved keys that need one; the overlay waits for a different boot_id.
  let restartKeys = $state<string[]>([]);
  let overlay = $state<{ step: 'waiting' | 'timeout'; detail: string } | null>(null);
  let watcher: ReturnType<typeof setInterval> | undefined;
  const storage = () => (typeof localStorage === 'undefined' ? undefined : localStorage);
  let showAdvanced = $state(loadShowAdvanced(storage()));

  const entries = $derived<any[]>(schema?.settings ?? []);
  const restartLabels = $derived(restartKeys.map((k) => entries.find((e) => e.key === k)?.label ?? k));
  const values = $derived<Record<string, any>>(loaded?.values ?? {});
  const secretsWritable = $derived(Boolean(loaded?.secrets_writable));
  const meta = $derived(SETTINGS_CATEGORIES.find((c) => c.id === category));
  const summaries = $derived<Record<string, string>>(
    Object.fromEntries((schema?.categories ?? []).map((c: any) => [c.id, c.summary])),
  );
  const view = $derived(categoryRows(schema, category, showAdvanced));
  const rows = $derived(view.rows.map((e: any) => describeRow(e, values[e.key], { secretsWritable })));
  const bootstrapRows = $derived(
    view.bootstrap.map((e: any) => describeRow(e, values[e.key], { secretsWritable })),
  );

  const valuesBody = $derived(buildValues(entries, values, drafts));
  $effect(() => {
    dirty = isDirty(valuesBody, null, null);
  });
  // A different category page starts clean: App has already asked before letting an edited page go.
  $effect(() => {
    void category;
    untrack(() => {
      drafts = {};
      errors = {};
      saveError = '';
      saveMessage = '';
    });
  });

  function setDraft(key: string, value: unknown) {
    drafts = { ...drafts, [key]: value };
    if (errors[key]) errors = { ...errors, [key]: '' };
  }

  async function load() {
    const seq = ++loadSeq;
    loading = true;
    loadError = '';
    try {
      const [s, v] = await Promise.all([
        schema ? Promise.resolve(schema) : api('/api/settings/schema'),
        api('/api/settings'),
      ]);
      if (seq !== loadSeq) return;
      schema = s;
      loaded = v;
      statusMsg = 'Settings loaded.';
    } catch (exc) {
      if (seq !== loadSeq) return;
      loadError = exc instanceof Error ? exc.message : 'Could not load settings.';
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  /** Save the edited rows in one all-or-nothing PUT. Also what Ctrl+S runs (App calls it through bind:this). */
  export async function save() {
    if (saving || !dirty) return;
    saving = true;
    saveError = '';
    saveMessage = '';
    errors = {};
    try {
      const result = await api('/api/settings', {
        method: 'PUT',
        body: { values: valuesBody, revision: loaded?.revision },
      });
      drafts = {};
      saveMessage = 'Saved.';
      await load();
      if (Array.isArray(result?.restart_required) && result.restart_required.length) {
        restartKeys = result.restart_required;
      }
    } catch (exc) {
      if (exc instanceof ApiError) {
        errors = fieldErrors(exc.payload as { errors?: unknown });
        saveError = Object.keys(errors).length
          ? ''
          : describeSaveError(exc.status, exc.payload as { error?: unknown });
        if (exc.status === 409) await load(); // the page now shows the current values; the edits stay for review
      } else {
        saveError = exc instanceof Error ? exc.message : 'Could not save settings.';
      }
    } finally {
      saving = false;
    }
  }

  function stopWatching() {
    if (watcher) clearInterval(watcher);
    watcher = undefined;
  }

  /** Ask the builder for a soft stop, then wait for a server with a different boot_id: the old one keeps answering meanwhile. */
  async function restartNow() {
    restartKeys = [];
    saveError = '';
    try {
      const reply = await api('/api/system/restart', { method: 'POST', body: {} });
      watchRestart(String(reply?.boot_id ?? ''));
    } catch (exc) {
      saveError =
        exc instanceof ApiError
          ? describeSaveError(exc.status, exc.payload as { error?: unknown })
          : 'Could not ask for a restart.';
    }
  }

  function watchRestart(oldBootId: string) {
    const startedAt = Date.now();
    stopWatching();
    overlay = { step: 'waiting', detail: describeRestartWait(null) };
    watcher = setInterval(async () => {
      let status: any = null;
      try {
        status = await api('/api/status?limit=1');
      } catch (exc) {
        status = exc instanceof ApiError ? exc.payload : null; // a 503 while the cache warms still names the boot
      }
      if (!watcher) return; // stopped while this poll was in flight
      const step = restartStep({ oldBootId, startedAt, now: Date.now(), status });
      if (step === 'back') {
        stopWatching();
        overlay = null;
        saveMessage = 'The builder restarted.';
        await load();
      } else if (step === 'timeout') {
        stopWatching();
        overlay = { step, detail: '' };
      } else {
        overlay = { step, detail: describeRestartWait(status) };
      }
    }, RESTART_POLL_MS);
  }

  onMount(() => {
    void load();
  });
  onDestroy(stopWatching);
</script>

<section aria-label="Settings">
  <header class="page-header">
    <h1 tabindex="-1">{meta ? meta.label : 'Settings'}</h1>
    <div class="settings-toolbar">
      <label class="settings-advanced">
        <input
          type="checkbox"
          checked={showAdvanced}
          onchange={(e) => {
            showAdvanced = e.currentTarget.checked;
            saveShowAdvanced(storage(), showAdvanced);
          }}
        />
        Show Advanced
      </label>
      <button class="primary" type="button" disabled={!dirty || saving} onclick={() => void save()}>
        {saveLabel(dirty)}
      </button>
    </div>
  </header>
  {#if meta}<p class="page-sub">{summaries[meta.id] ?? ''}</p>{/if}

  {#if loadError}<p class="notice failure" role="alert">{loadError}</p>{/if}
  {#if statusMsg}<p class="visually-hidden" role="status">{statusMsg}</p>{/if}
  {#if saveError}<p class="notice failure" role="alert">{saveError}</p>{/if}
  {#if saveMessage}<p class="notice success" role="status">{saveMessage}</p>{/if}
  {#if loaded?.restart_pending && !overlay}
    <p class="notice info-notice" role="status">
      Restart pending: saved settings that apply at a restart are not running yet.
      <button class="secondary" type="button" onclick={() => void restartNow()}>Restart Now</button>
    </p>
  {/if}

  {#if !schema || !loaded}
    {#if loading}<p class="page-sub">Loading settings…</p>{/if}
  {:else if !meta}
    <ul class="settings-grid" aria-label="Settings categories">
      {#each SETTINGS_CATEGORIES as c (c.id)}
        <li>
          <a class="settings-card" href={settingsHash(c.id)}>
            <h3>{c.label}</h3>
            <p>{summaries[c.id] ?? ''}</p>
          </a>
        </li>
      {/each}
    </ul>
  {:else}
    <div class="setting-rows">
      {#each rows as row (row.key)}
        <SettingRow
          {row}
          draft={drafts[row.key]}
          error={errors[row.key] ?? ''}
          onchange={(value) => setDraft(row.key, value)}
          onreset={() => setDraft(row.key, RESET)}
        />
      {/each}
    </div>
    {#if bootstrapRows.length}
      <section class="settings-section" aria-label="Bootstrap">
        <h2>Bootstrap</h2>
        <p class="page-sub">These values are fixed by the container before it can read the settings store.</p>
        <div class="setting-rows">
          {#each bootstrapRows as row (row.key)}
            <SettingRow {row} />
          {/each}
        </div>
      </section>
    {/if}
  {/if}

  <!-- The login plan's account tools live on the General page, for admins only. -->
  {#if meta?.id === 'general' && isAdmin(role)}<Security /><Accounts />{/if}
</section>

{#if restartKeys.length}
  <RestartDialog
    labels={restartLabels}
    portChanged={restartKeys.includes('REVIEW_PORT')}
    onlater={() => (restartKeys = [])}
    onnow={() => void restartNow()}
  />
{/if}
{#if overlay}
  <RestartOverlay step={overlay.step} detail={overlay.detail} onclose={() => (overlay = null)} />
{/if}

<style>
  .settings-toolbar {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .settings-advanced {
    display: flex;
    gap: 6px;
    align-items: center;
    cursor: pointer;
  }
  .settings-grid {
    list-style: none;
    margin: 4px 0 8px;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 18rem), 1fr));
    gap: 12px;
  }
  .settings-card {
    display: block;
    height: 100%;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    color: var(--text);
    text-decoration: none;
  }
  .settings-card:hover {
    background: var(--surface);
  }
  .settings-card:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }
  .settings-card h3 {
    margin: 0 0 4px;
  }
  .settings-card p {
    margin: 0;
    color: var(--muted);
  }
  .setting-rows {
    display: grid;
    gap: 10px;
    max-width: 52rem;
  }
  .settings-section {
    margin-top: 28px;
  }
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
</style>
