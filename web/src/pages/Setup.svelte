<script lang="ts">
  import { ChevronRight, LoaderCircle, ShieldCheck, UserPlus } from '@lucide/svelte';
  import { ApiError } from '../lib/api.js';
  import { login, setupAccount } from '../lib/session.js';

  let {
    onsignedin,
    onalreadysetup,
  }: {
    onsignedin: (user: { username: string; role: string }) => void;
    onalreadysetup: (message: string) => void;
  } = $props();
  let username = $state('');
  let password = $state('');
  let confirm = $state('');
  let busy = $state(false);
  let error = $state('');

  async function submit(e: Event) {
    e.preventDefault();
    error = '';
    if (password !== confirm) {
      error = 'Passwords do not match.';
      return;
    }
    busy = true;
    try {
      await setupAccount({ username, password });
      const user = await login({ username, password, remember: false });
      onsignedin(user);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 409) {
        // Someone else finished setup while this page was open: there is nothing left to create here.
        onalreadysetup('An account was created while this page was open. Sign in with it.');
        return;
      }
      error = exc instanceof Error ? exc.message : 'Setup failed.';
    } finally {
      busy = false;
    }
  }
</script>

<section class="login-panel">
  <form class="login-form" onsubmit={submit}>
    <div class="login-lock"><UserPlus size={24} /></div>
    <h1>Create the first admin account</h1>
    <p>Nobody has an account yet. This account manages settings, runs and everyone else's access.</p>
    <label for="setup-username">Username</label><input
      id="setup-username"
      type="text"
      bind:value={username}
      autocomplete="username"
      autocapitalize="none"
      spellcheck="false"
    />
    <label for="setup-password">Password</label><input
      id="setup-password"
      type="password"
      bind:value={password}
      autocomplete="new-password"
    />
    <label for="setup-confirm">Confirm password</label><input
      id="setup-confirm"
      type="password"
      bind:value={confirm}
      autocomplete="new-password"
    />
    <small>At least 10 characters.</small>
    <button class="primary" disabled={busy}
      >{#if busy}<LoaderCircle class="spin" size={17} />{:else}<ChevronRight size={17} />{/if}{busy
        ? 'Creating…'
        : 'Create account'}</button
    >{#if error}<p class="inline-error" role="alert">{error}</p>{/if}<small
      ><ShieldCheck size={14} />Stored as a salted scrypt hash on the config volume.</small
    >
  </form>
</section>
