<script lang="ts">
  import { ChevronRight, LoaderCircle, LockKeyhole, ShieldCheck } from '@lucide/svelte';
  import { ApiError } from '../lib/api.js';
  import { login } from '../lib/session.js';

  let {
    onsignedin,
    notice = '',
  }: { onsignedin: (user: { username: string; role: string }) => void; notice?: string } = $props();
  let username = $state('');
  let password = $state('');
  let remember = $state(false);
  let busy = $state(false);
  let error = $state('');

  async function submit(e: Event) {
    e.preventDefault();
    busy = true;
    error = '';
    try {
      const user = await login({ username, password, remember });
      password = '';
      onsignedin(user);
    } catch (exc) {
      const retry =
        exc instanceof ApiError
          ? (exc.payload as { retry_after?: number } | undefined)?.retry_after
          : undefined;
      error =
        (exc instanceof Error ? exc.message : 'Sign-in failed.') + (retry ? ` Try again in ${retry} s.` : '');
    } finally {
      busy = false;
    }
  }
</script>

<section class="login-panel">
  <form class="login-form" onsubmit={submit}>
    <div class="login-lock"><LockKeyhole size={24} /></div>
    <h1>Open your review workspace</h1>
    <p>Sign in with your DubTitlerr account.</p>
    <label for="username">Username</label><input
      id="username"
      name="username"
      type="text"
      bind:value={username}
      autocomplete="username"
      autocapitalize="none"
      spellcheck="false"
    />
    <label for="password">Password</label><input
      id="password"
      name="password"
      type="password"
      bind:value={password}
      autocomplete="current-password"
    />
    <label class="remember" for="remember"
      ><input id="remember" type="checkbox" bind:checked={remember} /> Keep me signed in for 30 days</label
    >
    <button class="primary" disabled={busy}
      >{#if busy}<LoaderCircle class="spin" size={17} />{:else}<ChevronRight size={17} />{/if}{busy
        ? 'Signing in…'
        : 'Sign in'}</button
    >{#if error || notice}<p class="inline-error" role="alert">{error || notice}</p>{/if}<small
      ><ShieldCheck size={14} />Your session stays in this browser. No external services.</small
    >
  </form>
</section>
