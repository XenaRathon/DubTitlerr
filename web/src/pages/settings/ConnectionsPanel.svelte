<script lang="ts">
  import {
    CLEAR,
    blankConnection,
    describeTestResult,
    parseExtraBody,
    stageChoices,
  } from '../../lib/settingsModel.js';

  type Connection = { name: string; kind: string; [field: string]: any };
  let {
    rules,
    saved,
    working = $bindable([]),
    picks = $bindable({}),
    errors = {},
    secretsWritable,
    canEdit = true,
    api,
  }: {
    /** `connections` from GET /api/settings/schema: the kinds and what each stage accepts. */
    rules: any;
    /** The connections the server holds, to tell a saved one (testable) from a new or edited one. */
    saved: Connection[];
    working?: Connection[];
    picks?: Record<string, string>;
    /** Field messages from a refused save: "connections.<name or index>.<field>" and "stages.<stage>". */
    errors?: Record<string, string>;
    secretsWritable: boolean;
    /** False for a reviewer: the page shows the connections and stage picks but changes nothing. */
    canEdit?: boolean;
    api: (path: string, options?: { method?: string; body?: object }) => Promise<any>;
  } = $props();

  const STAGES: Array<[string, string]> = [
    ['repair', 'Repair'],
    ['restore', 'Punctuation restore'],
    ['verify', 'Glossary verify'],
    ['decision', 'Decision model'],
    ['acquire', 'Acquire'],
  ];
  const KIND_LABELS: Record<string, string> = {
    llamacpp: 'llama.cpp',
    ollama: 'Ollama',
    openai: 'OpenAI-compatible',
  };
  let results = $state<Record<string, { ok: boolean; text: string }>>({});
  let testing = $state<Record<string, boolean>>({});

  const label = (c: Connection, i: number) => c.name || String(i);
  const fieldError = (c: Connection, i: number, field: string) =>
    errors[`connections.${label(c, i)}.${field}`] ?? '';
  const savedCopy = (c: Connection) => saved.find((s) => s.name === c.name);
  /** A connection can be tested only as the server holds it: unedited and already saved. */
  const testable = (c: Connection) => {
    const s = savedCopy(c);
    return Boolean(
      s &&
      ['kind', 'url', 'model', 'timeout_connect', 'timeout_read'].every((f) => s[f] === c[f]) &&
      JSON.stringify(s.extra_body) === JSON.stringify(c.extra_body) &&
      c.key === undefined,
    );
  };
  const urlChanged = (c: Connection) => {
    const s = savedCopy(c);
    return Boolean(s && s.api_key?.set && (s.url !== c.url || s.kind !== c.kind) && c.key === undefined);
  };

  function add() {
    working = [...working, blankConnection(rules)];
  }
  function remove(i: number) {
    working = working.filter((_, n) => n !== i);
  }
  function update(i: number, patch: Partial<Connection>) {
    working = working.map((c, n) => (n === i ? { ...c, ...patch } : c));
  }
  /** The body as loaded: the server's {set} marker for a saved connection, {} for a new one. Sending it back keeps the body. */
  const keptBody = (c: Connection) => savedCopy(c)?.extra_body ?? {};
  const bodySet = (c: Connection) => Boolean(savedCopy(c)?.extra_body?.set);
  function setExtra(i: number, text: string) {
    const c = working[i];
    if (text.trim() === '') {
      update(i, { extra_text: text, extra_error: '', extra_body: keptBody(c) });
      return;
    }
    const parsed = parseExtraBody(text);
    update(
      i,
      parsed.error
        ? { extra_text: text, extra_error: parsed.error }
        : { extra_text: text, extra_error: '', extra_body: parsed.value },
    );
  }
  function pick(stage: string, value: string) {
    picks = { ...picks, [stage]: value };
  }

  async function run(slot: string, body: object) {
    if (testing[slot]) return;
    testing[slot] = true;
    try {
      const res = await api('/api/settings/test', { method: 'POST', body });
      results[slot] = { ok: res?.ok === true, text: describeTestResult(res) };
    } catch (exc) {
      results[slot] = { ok: false, text: exc instanceof Error ? exc.message : 'The test could not run.' };
    } finally {
      testing[slot] = false;
    }
  }
</script>

<section class="connections" aria-label="Connections">
  <h2>Connections</h2>
  <p class="page-sub">
    A connection is an LLM server a stage talks to. Pick one for each stage below; a stage with none keeps the
    container's own settings.
  </p>

  {#each working as c, i (i)}
    <fieldset class="connection" data-connection={i} disabled={!canEdit}>
      <legend>Connection {c.name || '(new)'}</legend>
      <div class="field">
        <label for={`conn-${i}-name`}>Name</label>
        <input
          id={`conn-${i}-name`}
          type="text"
          value={c.name}
          readonly={Boolean(savedCopy(c))}
          autocomplete="off"
          spellcheck="false"
          oninput={(e) => update(i, { name: e.currentTarget.value })}
        />
        {#if fieldError(c, i, 'name')}<p class="field-error" role="alert">{fieldError(c, i, 'name')}</p>{/if}
      </div>
      <div class="field">
        <label for={`conn-${i}-kind`}>Kind</label>
        <select
          id={`conn-${i}-kind`}
          value={c.kind}
          onchange={(e) => update(i, { kind: e.currentTarget.value })}
        >
          {#each rules?.kinds ?? [] as kind (kind)}<option value={kind}>{KIND_LABELS[kind] ?? kind}</option
            >{/each}
        </select>
        {#if fieldError(c, i, 'kind')}<p class="field-error" role="alert">{fieldError(c, i, 'kind')}</p>{/if}
      </div>
      <div class="field">
        <label for={`conn-${i}-url`}>URL</label>
        <input
          id={`conn-${i}-url`}
          type="text"
          value={c.url}
          autocomplete="off"
          spellcheck="false"
          placeholder="http://192.168.1.20:8090/v1/chat/completions"
          oninput={(e) => update(i, { url: e.currentTarget.value })}
        />
        {#if urlChanged(c)}<p class="hint">
            Changing the URL clears the stored key unless you type the key again.
          </p>{/if}
        {#if fieldError(c, i, 'url')}<p class="field-error" role="alert">{fieldError(c, i, 'url')}</p>{/if}
      </div>
      <div class="field">
        <label for={`conn-${i}-model`}>Model</label>
        <input
          id={`conn-${i}-model`}
          type="text"
          value={c.model}
          autocomplete="off"
          spellcheck="false"
          oninput={(e) => update(i, { model: e.currentTarget.value })}
        />
        {#if fieldError(c, i, 'model')}<p class="field-error" role="alert">
            {fieldError(c, i, 'model')}
          </p>{/if}
      </div>
      {#if c.kind === 'openai'}
        <div class="field">
          {#if secretsWritable && canEdit}
            <label for={`conn-${i}-key`}>API key</label>
            <input
              id={`conn-${i}-key`}
              type="password"
              autocomplete="new-password"
              spellcheck="false"
              value={typeof c.key === 'string' ? c.key : ''}
              placeholder={c.api_key?.set ? 'Set. Type to replace it.' : 'Not set'}
              oninput={(e) =>
                update(i, { key: e.currentTarget.value === '' ? undefined : e.currentTarget.value })}
            />
            {#if c.api_key?.set && c.key !== CLEAR}
              <button class="secondary" type="button" onclick={() => update(i, { key: CLEAR })}
                >Clear key</button
              >
            {/if}
            {#if c.key === CLEAR}<span class="hint">The key is cleared when you save.</span>{/if}
          {:else}
            <p class="field-label">API key: {c.api_key?.set ? 'Set' : 'Not set'}</p>
            {#if !secretsWritable}<p class="hint">available after login is enabled</p>{/if}
          {/if}
          {#if fieldError(c, i, 'api_key')}<p class="field-error" role="alert">
              {fieldError(c, i, 'api_key')}
            </p>{/if}
        </div>
        <div class="field">
          <p class="field-label extra-state">Extra request body: {bodySet(c) ? 'Set' : 'Not set'}</p>
          <label for={`conn-${i}-extra`}>Replace body</label>
          <!-- Write-only, like the key: the stored body never comes back. Type a JSON object to replace it; {} removes it. -->
          <textarea
            id={`conn-${i}-extra`}
            rows="2"
            spellcheck="false"
            placeholder={'{"reasoning": {"effort": "low"}}'}
            aria-describedby={`conn-${i}-extra-hint`}
            value={c.extra_text ?? ''}
            oninput={(e) => setExtra(i, e.currentTarget.value)}></textarea>
          <p class="hint" id={`conn-${i}-extra-hint`}>
            Leave empty to keep the stored body; {'{}'} removes it.
          </p>
          {#if c.extra_error}<p class="field-error" role="alert">{c.extra_error}</p>{/if}
          {#if fieldError(c, i, 'extra_body')}<p class="field-error" role="alert">
              {fieldError(c, i, 'extra_body')}
            </p>{/if}
        </div>
      {/if}
      <div class="field inline">
        <label for={`conn-${i}-tc`}>Connect timeout (s)</label>
        <input
          id={`conn-${i}-tc`}
          type="text"
          inputmode="decimal"
          value={c.timeout_connect}
          oninput={(e) =>
            update(i, { timeout_connect: Number(e.currentTarget.value) || e.currentTarget.value })}
        />
        <label for={`conn-${i}-tr`}>Read timeout (s)</label>
        <input
          id={`conn-${i}-tr`}
          type="text"
          inputmode="decimal"
          value={c.timeout_read}
          oninput={(e) => update(i, { timeout_read: Number(e.currentTarget.value) || e.currentTarget.value })}
        />
        {#each ['timeout_connect', 'timeout_read'] as field (field)}
          {#if fieldError(c, i, field)}<p class="field-error" role="alert">{fieldError(c, i, field)}</p>{/if}
        {/each}
      </div>
      <div class="actions">
        {#if canEdit}
          <button
            class="secondary"
            type="button"
            disabled={!testable(c) || testing[`conn:${c.name}`]}
            title={testable(c) ? '' : 'Save this connection first'}
            onclick={() => void run(`conn:${c.name}`, { connection: c.name })}
            >Test connection {c.name}</button
          >
          <button
            class="secondary"
            type="button"
            aria-label={`Remove connection ${c.name || 'new'}`}
            onclick={() => remove(i)}>Remove</button
          >
        {/if}
      </div>
      {#if results[`conn:${c.name}`]}
        <p
          id={`conn-${i}-result`}
          class={['notice', results[`conn:${c.name}`].ok ? 'success' : 'failure']}
          role={results[`conn:${c.name}`].ok ? 'status' : 'alert'}
        >
          {results[`conn:${c.name}`].text}
        </p>
      {/if}
    </fieldset>
  {/each}
  {#if canEdit}<button class="secondary" type="button" onclick={add}>Add connection</button>{/if}

  <h3 class="stages-title">Stages</h3>
  <div class="stages">
    {#each STAGES as [stage, title] (stage)}
      {@const choices = stageChoices(rules, stage, working)}
      <div class="field inline">
        <label for={`stage-${stage}`}>{title} connection</label>
        <select
          id={`stage-${stage}`}
          value={picks[stage] ?? ''}
          disabled={!canEdit}
          onchange={(e) => pick(stage, e.currentTarget.value)}
        >
          <option value="">(container environment)</option>
          {#each choices as choice (choice.value)}<option value={choice.value}>{choice.label}</option>{/each}
        </select>
        {#if canEdit && ['repair', 'verify', 'acquire'].includes(stage) && !(picks[stage] ?? '')}
          <button
            class="secondary"
            type="button"
            disabled={testing[`env:${stage}`]}
            onclick={() => void run(`env:${stage}`, { backend: stage })}
            >Test {stage} environment settings</button
          >
          {#if results[`env:${stage}`]}
            <span
              id={`env-result-${stage}`}
              class={results[`env:${stage}`].ok ? 'ok' : 'bad'}
              role={results[`env:${stage}`].ok ? 'status' : 'alert'}>{results[`env:${stage}`].text}</span
            >
          {/if}
        {/if}
        {#if errors[`stages.${stage}`]}<p class="field-error" role="alert">
            {errors[`stages.${stage}`]}
          </p>{/if}
      </div>
    {/each}
  </div>
</section>

<style>
  .connections {
    margin-top: 8px;
    max-width: 52rem;
  }
  .connection {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    margin: 0 0 10px;
    display: grid;
    gap: 8px;
  }
  .connection legend {
    padding: 0 6px;
    font-weight: 600;
  }
  .field {
    display: grid;
    gap: 4px;
  }
  .field.inline {
    grid-template-columns: repeat(auto-fit, minmax(10rem, max-content));
    align-items: center;
    gap: 8px;
  }
  .field input[type='text'],
  .field input[type='password'],
  .field select,
  .field textarea {
    max-width: 36rem;
    min-width: 0;
  }
  .field-label {
    margin: 0;
    font-weight: 600;
  }
  .hint {
    margin: 0;
    color: var(--muted);
  }
  .field-error {
    margin: 0;
    color: var(--bad);
  }
  .actions {
    display: flex;
    gap: 8px;
  }
  .stages-title {
    margin: 18px 0 6px;
  }
  .ok {
    color: var(--ok);
  }
  .bad {
    color: var(--bad);
  }
</style>
