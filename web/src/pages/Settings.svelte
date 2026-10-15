<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { ApiError } from '../lib/api.js';
  import { CircleCheck, CircleMinus } from '@lucide/svelte';
  import {
    buildSettingsBody,
    describeAcquireApply,
    describePendingAcquireApply,
    describeTestResult,
    describeWriteError,
    formatValue,
    groupSettings,
    allowedChoices,
    pendingEntries,
    secretBadges,
    sourceNote,
    validateModel,
  } from '../lib/settings.js';
  import { isAdmin } from '../lib/roles.js';

  // The options-style wrapper the Runs page uses: api(path, { method, body, headers }).
  let {
    api,
    role = 'user',
  }: {
    api: (
      path: string,
      options?: { method?: string; body?: object; headers?: Record<string, string> },
    ) => Promise<any>;
    role?: string;
  } = $props();

  // The server's allow-lists (RUNTIME_VERIFY_BACKENDS, RUNTIME_DECISION_MODELS); a PUT outside them is refused.
  let allowedVerify = $state<unknown>([]);
  let allowedModels = $state<unknown>([]);

  const BACKENDS = ['repair', 'verify', 'acquire'] as const;
  type Backend = (typeof BACKENDS)[number];

  interface TestOutcome {
    ok: boolean;
    latency_ms: number;
    error: string;
    status?: number;
  }

  let settings = $state<Record<string, string>>({});
  let secrets = $state<Record<string, boolean>>({});
  let source = $state('');
  let profiles = $state<string[]>([]);
  let pending = $state<Record<string, unknown>>({});
  let writable = $state(true);
  let editProfile = $state('');
  let editModel = $state('');
  let editVerifyBackend = $state('');
  let editVerifyModel = $state('');
  let editRequireEng = $state(false);
  let acquireApply = $state<{ enabled?: boolean; source?: string } | null>(null);
  let editAcquireApply = $state(true);
  let saving = $state(false);
  let resetting = $state(false);
  let writeError = $state('');
  let writeMsg = $state('');
  let writeFormError = $state('');
  let loading = $state(false);
  let loadSeq = 0;
  let errorMsg = $state('');
  let statusMsg = $state('');
  let testing = $state<Record<string, boolean>>({});
  let results = $state<Record<string, TestOutcome | undefined>>({});

  const groups = $derived(groupSettings(settings));
  const badges = $derived(secretBadges(secrets));
  const pendingList = $derived(pendingEntries(pending));
  const pendingFor = (key: string) => pendingList.find((e) => e.key === key)?.value;
  const saved = (key: string) => (typeof settings[key] === 'string' ? settings[key] : '');
  const verifyChoices = $derived(allowedChoices(allowedVerify, saved('verify_backend')));
  const modelChoices = $derived(allowedChoices(allowedModels, saved('verify_decision_model')));
  const noModels = $derived(!modelChoices.some((c) => !c.disabled));

  function seedEdits() {
    const text = (key: string) => {
      const v = settings[key];
      return typeof v === 'string' ? v : '';
    };
    editProfile = text('repair_profile');
    editModel = text('repair_model');
    editVerifyBackend = text('verify_backend');
    editVerifyModel = text('verify_decision_model');
    const flag = String(settings['require_eng'] ?? '');
    editRequireEng = flag === 'true' || flag === '1';
    // Unset means apply, so seed from the server's effective value, not from the raw string.
    editAcquireApply = acquireApply?.enabled ?? true;
  }

  function reportWriteError(exc: unknown, fallback: string) {
    if (exc instanceof ApiError)
      writeError = describeWriteError(exc.status, exc.payload as { error?: unknown });
    else writeError = exc instanceof Error ? exc.message : fallback;
  }

  async function saveSettings() {
    if (saving) return;
    writeFormError = '';
    writeError = '';
    writeMsg = '';
    const edited = {
      repair_profile: editProfile,
      repair_model: editModel,
      verify_backend: editVerifyBackend,
      verify_decision_model: editVerifyModel,
      requireEng: editRequireEng,
      acquireApply: editAcquireApply,
    };
    for (const [label, value] of [
      ['Repair model', editModel],
      ['Verify decision model', editVerifyModel],
    ] as Array<[string, string]>) {
      if (value.trim() !== '' && validateModel(value) !== null) {
        writeFormError = `${label}: ${validateModel(value)}`;
        return;
      }
    }
    const body = buildSettingsBody(settings, edited, acquireApply);
    if (Object.keys(body).length === 0) {
      writeMsg = 'Nothing changed.';
      return;
    }
    saving = true;
    try {
      await api('/api/settings', { method: 'PUT', body });
      writeMsg = 'Saved. Overrides apply at the next sweep.';
      await load();
    } catch (exc) {
      reportWriteError(exc, 'Could not save settings.');
    } finally {
      saving = false;
    }
    await tick();
    document.getElementById('settings-save')?.focus();
  }

  async function resetOverrides() {
    if (resetting) return;
    if (!window.confirm('Delete all runtime overrides and go back to the container environment?')) return;
    writeError = '';
    writeMsg = '';
    resetting = true;
    try {
      await api('/api/settings/reset', { method: 'POST' });
      writeMsg = 'Overrides cleared.';
      await load();
    } catch (exc) {
      reportWriteError(exc, 'Could not reset overrides.');
    } finally {
      resetting = false;
    }
    await tick();
    document.getElementById('settings-save')?.focus();
  }

  // Plain names for the reported keys; anything new falls back to the key with spaces, so nothing is hidden.
  const LABELS: Record<string, string> = {
    repair_backend: 'Repair backend',
    repair_model: 'Repair model',
    repair_llamacpp_url: 'Local LLM server URL',
    repair_openai_url: 'OpenAI-compatible URL',
    repair_unanchored: 'Unanchored repair',
    verify_backend: 'Verify backend',
    verify_decision_model: 'Verify decision model',
    acquire_backend: 'Acquire backend',
    glossary_arc_tags: 'Glossary arc tags',
    whisper_model: 'Whisper model',
    compute_type: 'Compute type',
    require_eng: 'Require English audio',
    acquire_apply: 'Apply acquired names',
    rescan_interval: 'Rescan interval',
    merge_window: 'Container window',
    merge_roots: 'Library roots',
    anime_order: 'Anime order file',
  };
  function labelFor(key: string) {
    return LABELS[key] ?? key.replace(/_/g, ' ');
  }
  // Unset values fold away under a disclosure so the set ones are what the eye lands on.
  function splitEntries(entries: Array<{ key: string; value: unknown }>) {
    const set = entries.filter(({ key, value }) => formatValue(key, value) !== 'not set');
    const unset = entries.filter(({ key, value }) => formatValue(key, value) === 'not set');
    return { set, unset };
  }

  function toOutcome(exc: unknown): TestOutcome {
    const msg = exc instanceof Error ? exc.message : 'Request failed. Please try again.';
    // The status comes from the thrown ApiError: the server's own error text replaces "Request failed (N)" in msg.
    const status = exc instanceof ApiError ? exc.status : undefined;
    return { ok: false, latency_ms: 0, error: msg, ...(status !== undefined ? { status } : {}) };
  }

  async function load() {
    if (loading) return;
    loading = true;
    errorMsg = '';
    const seq = ++loadSeq;
    try {
      const data = (await api('/api/settings')) as {
        settings: Record<string, string>;
        secrets: Record<string, boolean>;
        source: string;
        profiles?: string[];
        pending?: Record<string, unknown>;
        acquire_apply?: { enabled?: boolean; source?: string };
        writable?: boolean;
        allowed_verify_backends?: unknown;
        allowed_decision_models?: unknown;
      };
      if (seq !== loadSeq) return;
      settings = data.settings;
      secrets = data.secrets;
      source = data.source;
      profiles = Array.isArray(data.profiles) ? data.profiles : [];
      acquireApply = data.acquire_apply ?? null;
      pending = data.pending !== null && typeof data.pending === 'object' ? data.pending : {};
      writable = data.writable !== false;
      allowedVerify = data.allowed_verify_backends ?? [];
      allowedModels = data.allowed_decision_models ?? [];
      seedEdits();
      statusMsg = 'Settings loaded.';
    } catch (exc) {
      if (seq !== loadSeq) return;
      errorMsg = exc instanceof Error ? exc.message : 'Could not load settings.';
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  async function testBackend(name: Backend) {
    if (testing[name]) return;
    testing[name] = true;
    try {
      const res = (await api('/api/settings/test', { body: { backend: name } })) as TestOutcome;
      results[name] = {
        ok: res.ok === true,
        latency_ms: typeof res.latency_ms === 'number' ? res.latency_ms : 0,
        error: typeof res.error === 'string' ? res.error : '',
      };
    } catch (exc) {
      results[name] = toOutcome(exc);
    } finally {
      testing[name] = false;
    }
    await tick();
    document.getElementById(`settings-test-${name}`)?.focus();
  }

  onMount(() => {
    void load();
  });
</script>

<section aria-label="Settings">
  <header class="page-header">
    <h1 tabindex="-1">Settings</h1>
    <button class="secondary" type="button" disabled={loading} onclick={() => void load()}>
      Refresh settings
    </button>
  </header>
  <p class="page-sub">{sourceNote(source)}</p>

  {#if !writable}
    <p class="notice info-notice">
      Writes are disabled on this server. URLs and secrets stay in the compose file.
    </p>
  {/if}
  {#if errorMsg}<p class="notice failure" role="alert">{errorMsg}</p>{/if}
  {#if statusMsg}<p class="visually-hidden" role="status">{statusMsg}</p>{/if}

  {#if loading && groups.length === 0}
    <p class="page-sub">Loading settings…</p>
  {:else if groups.length === 0}
    <p class="page-sub">No settings reported.</p>
  {:else}
    <h2 class="settings-current">Current values</h2>
    <div class="settings-groups">
      {#each groups as group (group.title)}
        {@const parts = splitEntries(group.entries)}
        <article class="settings-card">
          <h3>{group.title}</h3>
          {#if parts.set.length}
            <dl class="settings-list">
              {#each parts.set as { key, value } (key)}
                <div>
                  <dt>{labelFor(key)}</dt>
                  <dd>{formatValue(key, value)}</dd>
                </div>
              {/each}
            </dl>
          {/if}
          {#if parts.unset.length}
            <details class="settings-unset">
              <summary>Not set ({parts.unset.length})</summary>
              <dl class="settings-list">
                {#each parts.unset as { key, value } (key)}
                  <div>
                    <dt>{labelFor(key)}</dt>
                    <dd>{formatValue(key, value)}</dd>
                  </div>
                {/each}
              </dl>
            </details>
          {/if}
        </article>
      {/each}
    </div>
  {/if}

  <section class="settings-section" aria-label="Secrets">
    <h2>Secrets</h2>
    {#if badges.length > 0}
      <div class="settings-secrets">
        {#each badges as { name, set } (name)}
          <span class="badge" data-tone={set ? 'ok' : 'muted'}
            >{#if set}<CircleCheck size={14} aria-hidden="true" />{:else}<CircleMinus
                size={14}
                aria-hidden="true"
              />{/if}{name}: {set ? 'set' : 'not set'}</span
          >
        {/each}
      </div>
    {:else}
      <p class="page-sub">No secrets tracked.</p>
    {/if}
  </section>

  <section class="settings-section" aria-label="Backend connectivity">
    <h2>Backend connectivity</h2>
    {#each BACKENDS as name (name)}
      <div class="settings-backend">
        <strong>{name}</strong>
        {#if isAdmin(role)}
          <button
            class="secondary"
            type="button"
            disabled={testing[name]}
            onclick={() => void testBackend(name)}>Test {name} connection</button
          >
          {#if results[name]}
            {#if results[name].ok}
              <p id={`settings-test-${name}`} tabindex="-1" class="notice success" role="status">
                {describeTestResult(results[name])}
              </p>
            {:else}
              <p id={`settings-test-${name}`} tabindex="-1" class="notice failure" role="alert">
                {describeTestResult(results[name])}
              </p>
            {/if}
          {/if}
        {/if}
      </div>
    {/each}
  </section>

  {#if writable && isAdmin(role)}
    <section class="settings-section settings-edit" aria-label="Edit settings">
      <h2>Edit settings</h2>
      <div id="settings-write-result" tabindex="-1">
        {#if writeFormError}<p class="notice failure" role="alert">{writeFormError}</p>{/if}
        {#if writeError}<p class="notice failure" role="alert">{writeError}</p>{/if}
        {#if writeMsg}<p class="notice success" role="status">{writeMsg}</p>{/if}
      </div>
      <form
        class="settings-form"
        onsubmit={(e) => {
          e.preventDefault();
          void saveSettings();
        }}
      >
        <label for="settings-profile">Repair profile</label>
        <select id="settings-profile" bind:value={editProfile} disabled={saving}>
          <option value="">(container default)</option>
          {#each profiles as name (name)}<option value={name}>{name}</option>{/each}
        </select>
        <label for="settings-model">Repair model</label>
        <input
          id="settings-model"
          bind:value={editModel}
          placeholder="qwen3-4b-instruct"
          autocomplete="off"
          spellcheck="false"
          disabled={saving}
        />
        {#if pendingFor('repair_model') !== undefined}<span class="badge neutral"
            >pending next sweep: {String(pendingFor('repair_model'))}</span
          >{/if}
        <label for="settings-verify-backend">Verify backend</label>
        <select id="settings-verify-backend" bind:value={editVerifyBackend} disabled={saving}>
          <option value="">(container default)</option>
          {#each verifyChoices as choice (choice.value)}
            <option value={choice.value} disabled={choice.disabled}>{choice.label}</option>
          {/each}
        </select>
        {#if pendingFor('verify_backend') !== undefined}<span class="badge neutral"
            >pending next sweep: {String(pendingFor('verify_backend'))}</span
          >{/if}
        {#if noModels}
          <!-- Nothing to choose: say why and how to enable it instead of offering an empty control. -->
          <span class="settings-label">Verify decision model</span>
          <p id="settings-verify-model" class="settings-unavailable">
            No decision models are enabled on this server; set RUNTIME_DECISION_MODELS{saved(
              'verify_decision_model',
            )
              ? `. Currently set to ${saved('verify_decision_model')}.`
              : ''}
          </p>
        {:else}
          <label for="settings-verify-model">Verify decision model</label>
          <select id="settings-verify-model" bind:value={editVerifyModel} disabled={saving}>
            <option value="">(container default)</option>
            {#each modelChoices as choice (choice.value)}
              <option value={choice.value} disabled={choice.disabled}>{choice.label}</option>
            {/each}
          </select>
        {/if}
        {#if pendingFor('verify_decision_model') !== undefined}<span class="badge neutral"
            >pending next sweep: {String(pendingFor('verify_decision_model'))}</span
          >{/if}
        <label class="settings-check"
          ><input type="checkbox" bind:checked={editRequireEng} disabled={saving} />Require English audio</label
        >
        {#if pendingFor('require_eng') !== undefined}<span class="badge neutral"
            >pending next sweep: {String(pendingFor('require_eng'))}</span
          >{/if}
        <label class="settings-check"
          ><input
            type="checkbox"
            bind:checked={editAcquireApply}
            aria-describedby="settings-acquire-apply-note"
            disabled={saving}
          />Apply acquired names</label
        >
        <small id="settings-acquire-apply-note" class="settings-hint"
          >{describeAcquireApply(acquireApply)}</small
        >
        {#if pendingFor('acquire_apply') !== undefined}<span class="badge neutral"
            >pending next sweep: {describePendingAcquireApply(pendingFor('acquire_apply'))}</span
          >{/if}
        <div class="settings-actions">
          <button id="settings-save" class="primary" type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save settings'}
          </button>
          <button
            class="secondary"
            type="button"
            disabled={saving || resetting}
            onclick={() => void resetOverrides()}>Reset overrides</button
          >
        </div>
      </form>
    </section>
  {/if}

  <p class="settings-note">
    Overrides apply at the next sweep; the builder keeps working with prior values until then. URLs and
    secrets stay in the compose file.
  </p>
</section>

<style>
  .settings-current {
    margin-bottom: 10px;
  }
  .settings-groups {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 26rem), 1fr));
    gap: 12px;
    margin: 4px 0 8px;
  }
  .settings-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    min-width: 0;
  }
  .settings-list {
    display: grid;
    gap: 6px;
    margin: 8px 0 0;
  }
  .settings-list > div {
    display: grid;
    grid-template-columns: minmax(8rem, 11rem) minmax(0, 1fr);
    gap: 12px;
  }
  .settings-list dt {
    color: var(--muted);
  }
  .settings-list dd {
    margin: 0;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .settings-unset {
    margin-top: 8px;
  }
  .settings-unset summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 13px;
    width: fit-content;
    min-height: 24px;
    line-height: 24px;
  }
  .settings-section {
    margin-top: 28px;
  }
  .settings-section h2 {
    margin-bottom: 10px;
  }
  .settings-secrets {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .settings-backend {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  .settings-backend strong {
    min-width: 5rem;
    font-weight: 500;
  }
  .settings-backend .notice {
    margin: 0;
  }
  .settings-hint,
  .settings-note {
    color: var(--muted);
  }
  .settings-note {
    margin-top: 28px;
  }
  .settings-edit .settings-form {
    display: grid;
    gap: 8px;
    max-width: 40rem;
  }
  .settings-edit .settings-label,
  .settings-unavailable {
    color: var(--muted);
  }
  .settings-unavailable {
    margin: 0;
  }
  .settings-edit .settings-actions {
    display: flex;
    gap: 8px;
    margin-top: 6px;
  }
  .settings-edit .settings-check {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .settings-edit .settings-form > label:not(.settings-check) {
    color: var(--muted);
  }
  .settings-edit .settings-form > .badge {
    justify-self: start;
  }
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  @media (min-width: 769px) {
    .settings-edit .settings-form {
      grid-template-columns: 11rem minmax(0, 1fr);
      align-items: center;
      column-gap: 16px;
    }
    .settings-edit .settings-form > .badge,
    .settings-edit .settings-form > .settings-check,
    .settings-edit .settings-form > .settings-actions {
      grid-column: 2;
    }
  }
</style>
