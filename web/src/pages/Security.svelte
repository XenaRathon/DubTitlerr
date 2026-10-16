<script lang="ts">
  import { onMount } from 'svelte';
  import { request } from '../lib/session.js';

  let key = $state('');
  let shown = $state(false);
  let status = $state('');
  let error = $state('');

  async function load() {
    try {
      key = ((await request('/api/apikey')) as { key: string }).key;
    } catch (exc) {
      error = exc instanceof Error ? exc.message : 'Could not load the API key.';
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(key);
      status = 'Copied.';
    } catch {
      shown = true;
      status = 'Copy is not available here; select the key and copy it by hand.';
    }
  }
  async function reset() {
    if (!window.confirm('Reset the API key? Scripts that use the current key stop working immediately.'))
      return;
    error = '';
    try {
      key = ((await request('/api/apikey/reset', { method: 'POST', body: {} })) as { key: string }).key;
      status = 'New key issued. The old key no longer works.';
    } catch (exc) {
      error = exc instanceof Error ? exc.message : 'Could not reset the API key.';
    }
  }
  onMount(load);
</script>

<section class="settings-section" aria-label="Security">
  <h2>Security</h2>
  <p>
    Scripts and other apps send this key in the <code>X-Api-Key</code> header. It has administrator rights.
  </p>
  <label for="api-key">API key</label>
  <input
    id="api-key"
    readonly
    type={shown ? 'text' : 'password'}
    value={key}
    autocomplete="off"
    spellcheck="false"
  />
  <div class="settings-actions">
    <button class="secondary" type="button" onclick={() => (shown = !shown)}
      >{shown ? 'Hide key' : 'Show key'}</button
    >
    <button class="secondary" type="button" onclick={copy}>Copy</button>
    <button class="secondary" type="button" onclick={reset}>Reset key</button>
  </div>
  {#if error}<p class="notice failure" role="alert">{error}</p>{/if}
  {#if status}<p class="notice success" role="status">{status}</p>{/if}
</section>

<style>
  .settings-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
</style>
