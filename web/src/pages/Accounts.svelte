<script lang="ts">
  import { onMount } from 'svelte';
  import { request } from '../lib/session.js';

  type User = { name: string; role: string };
  let users = $state<User[]>([]);
  let username = $state('');
  let password = $state('');
  let role = $state('user');
  let resetPw = $state<Record<string, string>>({});
  let status = $state('');
  let error = $state('');

  async function load() {
    users = ((await request('/api/users')) as { users: User[] }).users;
  }
  async function run(done: string, action: () => Promise<unknown>) {
    error = '';
    status = '';
    try {
      await action();
      await load();
      status = done;
    } catch (exc) {
      error = exc instanceof Error ? exc.message : 'Request failed.';
    }
  }
  const url = (u: User) => `/api/users/${encodeURIComponent(u.name)}`;
  const add = (e: Event) => {
    e.preventDefault();
    return run('Account added.', async () => {
      await request('/api/users', { method: 'POST', body: { username, password, role } });
      username = password = '';
      role = 'user';
    });
  };
  const setRole = (u: User, next: string) =>
    run(`${u.name} is now ${next}.`, () => request(url(u), { method: 'PUT', body: { role: next } }));
  const setPassword = (u: User) =>
    run(`Password for ${u.name} reset; their sessions ended.`, async () => {
      await request(url(u), { method: 'PUT', body: { password: resetPw[u.name] } });
      resetPw[u.name] = '';
    });
  const remove = (u: User) => {
    if (!window.confirm(`Delete ${u.name}? Their sessions end immediately.`)) return;
    return run(`${u.name} deleted.`, () => request(url(u), { method: 'DELETE' }));
  };
  onMount(() => void run('', load));
</script>

<section class="settings-section" aria-label="Accounts">
  <h2>Accounts</h2>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="table-scroll" role="region" aria-label="Account list" tabindex="0">
    <table class="data-table">
      <thead><tr><th>Name</th><th>Role</th><th>Password</th><th></th></tr></thead>
      <tbody>
        {#each users as u (u.name)}
          <tr>
            <td>{u.name}</td>
            <td>
              <select
                aria-label={`Role for ${u.name}`}
                value={u.role}
                onchange={(e) => setRole(u, e.currentTarget.value)}
              >
                <option value="admin">admin</option><option value="user">user</option>
              </select>
            </td>
            <td>
              <input
                type="password"
                aria-label={`New password for ${u.name}`}
                bind:value={resetPw[u.name]}
                autocomplete="new-password"
              />
              <button class="secondary" type="button" onclick={() => setPassword(u)}>Reset password</button>
            </td>
            <td><button class="secondary" type="button" onclick={() => remove(u)}>Delete</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <form class="accounts-add" onsubmit={add}>
    <label for="new-username">New username</label>
    <input
      id="new-username"
      bind:value={username}
      autocomplete="off"
      autocapitalize="none"
      spellcheck="false"
    />
    <label for="new-password">New password</label>
    <input id="new-password" type="password" bind:value={password} autocomplete="new-password" />
    <label for="new-role">Role</label>
    <select id="new-role" bind:value={role}
      ><option value="user">user</option><option value="admin">admin</option></select
    >
    <button class="secondary">Add account</button>
  </form>
  {#if error}<p class="notice failure" role="alert">{error}</p>{/if}
  {#if status}<p class="notice success" role="status">{status}</p>{/if}
</section>

<style>
  /* A phone is narrower than the table: it scrolls inside its own region, and the add form wraps. */
  .accounts-add {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
  }
</style>
