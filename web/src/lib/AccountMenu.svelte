<script lang="ts">
  import { CircleUser, LogOut } from '@lucide/svelte';
  import { changePassword } from './session.js';

  let {
    username,
    role,
    onlogout,
    disabled = false,
  }: { username: string; role: string; onlogout: () => void; disabled?: boolean } = $props();
  let open = $state(false);
  let wrap = $state<HTMLDivElement>();
  let current = $state('');
  let next = $state('');
  let again = $state('');
  let busy = $state(false);
  let error = $state('');
  let done = $state('');

  async function submit(e: Event) {
    e.preventDefault();
    error = '';
    done = '';
    if (next !== again) {
      error = 'The new passwords do not match.';
      return;
    }
    busy = true;
    try {
      await changePassword({ current, next });
      current = next = again = '';
      done = 'Password changed. Your other sessions were signed out.';
    } catch (exc) {
      error = exc instanceof Error ? exc.message : 'Could not change the password.';
    } finally {
      busy = false;
    }
  }
  // A click anywhere outside the menu closes it, like Escape does.
  function outside(e: MouseEvent) {
    if (open && wrap && !wrap.contains(e.target as Node)) open = false;
  }
</script>

<svelte:window onclick={outside} />

<div
  class="account-menu-wrap"
  bind:this={wrap}
  onkeydown={(e) => e.key === 'Escape' && (open = false)}
  role="presentation"
>
  <button
    class="icon-button"
    aria-label="Account menu"
    aria-expanded={open}
    aria-controls="account-menu"
    onclick={() => (open = !open)}><CircleUser size={19} /></button
  >
  {#if open}
    <div id="account-menu" class="account-menu" role="region" aria-label="Account">
      <p><strong>{username}</strong> <span class="account-role">{role}</span></p>
      <form onsubmit={submit}>
        <label for="pw-current">Current password</label>
        <input id="pw-current" type="password" bind:value={current} autocomplete="current-password" />
        <label for="pw-new">New password</label>
        <input id="pw-new" type="password" bind:value={next} autocomplete="new-password" />
        <label for="pw-again">Confirm new password</label>
        <input id="pw-again" type="password" bind:value={again} autocomplete="new-password" />
        <button class="secondary" disabled={busy}>Change password</button>
        {#if error}<p class="inline-error" role="alert">{error}</p>{/if}
        {#if done}<p class="notice success" role="status">{done}</p>{/if}
      </form>
      <button class="secondary" type="button" {disabled} onclick={onlogout}
        ><LogOut size={16} />Sign out</button
      >
    </div>
  {/if}
</div>

<style>
  .account-menu-wrap {
    position: relative;
  }
  .account-menu {
    position: absolute;
    right: 0;
    top: calc(100% + 0.4rem);
    z-index: 20;
    display: grid;
    gap: 0.6rem;
    min-width: 17rem;
    padding: 1rem;
    background: var(--surface, #fff);
    border: 1px solid var(--border, #ccc);
    border-radius: 0.5rem;
  }
  .account-role {
    opacity: 0.7;
  }
</style>
