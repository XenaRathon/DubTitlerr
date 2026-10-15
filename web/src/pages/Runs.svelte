<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { ApiError } from '../lib/api.js';
  import {
    buildRequestBody,
    checkShowPick,
    commonZones,
    describeError,
    describeSchedule,
    formatWhen,
    scheduleBody,
    shortId,
    validateForm,
    validateSchedule,
  } from '../lib/runs.js';
  import StatusBadge from '../lib/StatusBadge.svelte';

  // Authenticated fetch wrapper: the session cookie and the CSRF header are added by session.js.
  let {
    api,
  }: {
    api: (
      path: string,
      options?: { method?: string; body?: object; headers?: Record<string, string> },
    ) => Promise<any>;
  } = $props();

  const POLL_MS = 15000;
  const ZONES = commonZones();

  interface RunRequest {
    id: string;
    show: string;
    season: number | null;
    episode_re: string | null;
    require_eng: number | null;
    status: string;
    created_at: string | null;
    finished_at: string | null;
    error: string | null;
  }

  let show = $state('');
  // Show directories from /api/shows. Empty (no library, or the load failed) means the field takes free text.
  let shows = $state.raw<string[]>([]);
  let showsFailed = $state(false);
  let season = $state('');
  let episodeRe = $state('');
  let requireEng = $state(false);
  let requests = $state<RunRequest[]>([]);
  let loading = $state(false);
  let queuing = $state(false);
  let loadSeq = 0;
  let pollTimer = 0;
  let errorMsg = $state('');
  let statusMsg = $state('');
  let formError = $state('');
  let schedEnabled = $state(false);
  let schedOpen = $state('00:00');
  let schedClose = $state('00:00');
  let schedTz = $state('UTC');
  let tzPlaceholder = $state('UTC');
  let schedLoading = $state(false);
  let schedSaving = $state(false);
  let schedError = $state('');
  let schedMsg = $state('');
  let schedFormError = $state('');

  // The muted line under the title: what the queue holds right now.
  const queueSummary = $derived.by(() => {
    if (!requests.length) return 'The queue is empty.';
    const pending = requests.filter((r) => r.status === 'pending').length;
    const running = requests.filter((r) => r.status === 'running').length;
    return `${pending} pending, ${running} running, ${requests.length} listed.`;
  });

  function reportError(exc: unknown, fallback: string) {
    if (exc instanceof ApiError)
      errorMsg = describeError(exc.status, exc.payload as { error?: unknown; existing_id?: unknown });
    else errorMsg = exc instanceof Error ? exc.message : fallback;
  }

  async function load() {
    if (loading) return;
    loading = true;
    const seq = ++loadSeq;
    try {
      const items = (await api('/api/requests')) as RunRequest[];
      if (seq !== loadSeq) return;
      requests = items;
    } catch (exc) {
      if (seq !== loadSeq) return;
      reportError(exc, 'Could not load requests.');
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  async function queue() {
    if (queuing) return;
    formError = '';
    errorMsg = '';
    statusMsg = '';
    const problem = validateForm({ show, season, episodeRe }) ?? checkShowPick(show, shows);
    if (problem) {
      formError = problem;
      return;
    }
    queuing = true;
    try {
      const res = (await api('/api/requests', {
        body: buildRequestBody({ show, season, episodeRe, requireEng }),
      })) as { id: string };
      statusMsg = `Queued as ${shortId(res.id)}.`;
      show = '';
      season = '';
      episodeRe = '';
      requireEng = false;
      await load();
    } catch (exc) {
      if (exc instanceof ApiError)
        errorMsg = describeError(exc.status, exc.payload as { error?: unknown; existing_id?: unknown });
      else errorMsg = exc instanceof Error ? exc.message : 'Could not queue the run.';
    } finally {
      queuing = false;
    }
    await tick();
    document.getElementById('runs-result')?.focus();
  }

  async function loadSchedule() {
    if (schedLoading) return;
    schedLoading = true;
    try {
      const data = (await api('/api/schedule')) as {
        enabled: boolean;
        open: string;
        close: string;
        tz: string;
      };
      schedEnabled = data.enabled === true;
      schedOpen = typeof data.open === 'string' ? data.open : '00:00';
      schedClose = typeof data.close === 'string' ? data.close : '00:00';
      schedTz = typeof data.tz === 'string' ? data.tz : 'UTC';
    } catch (exc) {
      if (exc instanceof ApiError)
        schedError = describeError(exc.status, exc.payload as { error?: unknown; existing_id?: unknown });
      else schedError = exc instanceof Error ? exc.message : 'Could not load the schedule.';
    } finally {
      schedLoading = false;
    }
  }

  async function saveSchedule() {
    if (schedSaving) return;
    schedFormError = '';
    schedError = '';
    schedMsg = '';
    const problem = validateSchedule({
      enabled: schedEnabled,
      open: schedOpen,
      close: schedClose,
      tz: schedTz,
    });
    if (problem) {
      schedFormError = problem;
      return;
    }
    schedSaving = true;
    try {
      await api('/api/schedule', {
        method: 'PUT',
        body: scheduleBody({ enabled: schedEnabled, open: schedOpen, close: schedClose, tz: schedTz }),
      });
      schedMsg = 'Schedule saved.';
    } catch (exc) {
      if (exc instanceof ApiError)
        schedError = describeError(exc.status, exc.payload as { error?: unknown; existing_id?: unknown });
      else schedError = exc instanceof Error ? exc.message : 'Could not save the schedule.';
    } finally {
      schedSaving = false;
    }
    await tick();
    document.getElementById('runs-schedule-result')?.focus();
  }

  async function loadShows() {
    try {
      const data = (await api('/api/shows')) as { shows?: unknown };
      shows = Array.isArray(data.shows) ? data.shows.filter((n): n is string => typeof n === 'string') : [];
    } catch {
      // Free text stays usable; the server still validates the name.
      showsFailed = true;
    }
  }

  onMount(() => {
    void loadShows();
    try {
      tzPlaceholder = Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
    } catch {
      /* Intl unavailable; the placeholder stays UTC */
    }
    void load();
    void loadSchedule();
    pollTimer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, POLL_MS);
    return () => {
      window.clearInterval(pollTimer);
    };
  });
</script>

<section aria-label="Run requests">
  <header class="page-header">
    <h1 tabindex="-1">Run requests</h1>
    <button class="secondary" type="button" disabled={loading} onclick={() => void load()}>Refresh</button>
  </header>
  <p class="page-sub">{queueSummary}</p>

  <div id="runs-result" tabindex="-1">
    {#if formError}<p class="notice failure" role="alert">{formError}</p>{/if}
    {#if errorMsg}<p class="notice failure" role="alert">{errorMsg}</p>{/if}
    {#if statusMsg}<p class="notice success" role="status">{statusMsg}</p>{/if}
  </div>

  <h2 class="runs-heading">Queue a run</h2>
  <form
    class="runs-form form-narrow"
    onsubmit={(e) => {
      e.preventDefault();
      void queue();
    }}
  >
    <label for="runs-show">Show</label>
    <input
      id="runs-show"
      list="runs-show-options"
      bind:value={show}
      placeholder={shows.length ? 'Type to filter shows' : 'Directory name under the anime root'}
      autocomplete="off"
      spellcheck="false"
      aria-describedby={showsFailed ? 'runs-show-hint' : undefined}
    />
    {#if showsFailed}<small id="runs-show-hint" class="runs-hint"
        >Show list unavailable; type the directory name.</small
      >{/if}
    <datalist id="runs-show-options">
      {#each shows as name (name)}<option value={name}></option>{/each}
    </datalist>
    <label for="runs-season">Season (optional)</label>
    <input id="runs-season" bind:value={season} inputmode="numeric" placeholder="e.g. 1" autocomplete="off" />
    <label for="runs-regex">Episode filter (optional)</label>
    <input
      id="runs-regex"
      bind:value={episodeRe}
      placeholder="Regex on the file name"
      autocomplete="off"
      spellcheck="false"
    />
    <label class="runs-check"><input type="checkbox" bind:checked={requireEng} />Require English audio</label>
    <div class="runs-actions">
      <button class="primary" type="submit" disabled={queuing}>Queue run</button>
    </div>
  </form>

  <h2 class="runs-heading">Queue</h2>
  {#if loading && requests.length === 0}
    <p class="page-sub">Loading requests…</p>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="table-scroll" role="region" aria-label="Request queue" tabindex="0">
      <table class="data-table runs-table">
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Show</th>
            <th scope="col">Season</th>
            <th scope="col">Filter</th>
            <th scope="col">Status</th>
            <th scope="col">Created</th>
            <th scope="col">Finished</th>
            <th scope="col">Error</th>
          </tr>
        </thead>
        <tbody>
          {#each requests as req (req.id)}
            <tr>
              <td title={req.id}><code>{shortId(req.id)}</code></td>
              <td>{req.show}</td>
              <td>{req.season ?? '—'}</td>
              <td>{req.episode_re ?? '—'}</td>
              <td><StatusBadge status={req.status} /></td>
              <td>{formatWhen(req.created_at)}</td>
              <td>{formatWhen(req.finished_at)}</td>
              <td>{req.error ?? '—'}</td>
            </tr>
          {:else}
            <tr><td class="empty-row" colspan="8">No requests yet.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="runs-note">Requests wait for the current show and for the schedule window.</p>
  {/if}

  <section class="runs-schedule" aria-label="Schedule">
    <h2 class="runs-heading">Schedule</h2>
    <div id="runs-schedule-result" tabindex="-1">
      {#if schedFormError}<p class="notice failure" role="alert">{schedFormError}</p>{/if}
      {#if schedError}<p class="notice failure" role="alert">{schedError}</p>{/if}
      {#if schedMsg}<p class="notice success" role="status">{schedMsg}</p>{/if}
    </div>
    <p class="runs-note">
      {describeSchedule({ enabled: schedEnabled, open: schedOpen, close: schedClose, tz: schedTz })}
    </p>
    {#if schedLoading}
      <p class="page-sub">Loading schedule…</p>
    {:else}
      <form
        class="runs-form form-narrow"
        onsubmit={(e) => {
          e.preventDefault();
          void saveSchedule();
        }}
      >
        <label class="runs-check"><input type="checkbox" bind:checked={schedEnabled} />Window enabled</label>
        <!-- With the window off the times are kept but not editable, so it is clear they do nothing yet. -->
        <label for="runs-open">Open</label>
        <input id="runs-open" type="time" bind:value={schedOpen} disabled={!schedEnabled} />
        <label for="runs-close">Close</label>
        <input id="runs-close" type="time" bind:value={schedClose} disabled={!schedEnabled} />
        <label for="runs-tz">Timezone</label>
        <input
          id="runs-tz"
          bind:value={schedTz}
          list="runs-tz-list"
          placeholder={tzPlaceholder}
          autocomplete="off"
          spellcheck="false"
          disabled={!schedEnabled}
        />
        <datalist id="runs-tz-list">
          {#each ZONES as zone (zone)}<option value={zone}></option>{/each}
        </datalist>
        <div class="runs-actions">
          <button class="primary" type="submit" disabled={schedSaving}>Save schedule</button>
        </div>
      </form>
    {/if}
    <p class="runs-note">Host systemd timers remain the outer guard.</p>
  </section>
</section>

<style>
  .runs-heading {
    font-size: 16px;
    margin: 24px 0 10px;
  }
  .form-narrow {
    max-width: 40rem;
  }
  .runs-hint,
  .runs-note {
    color: var(--muted);
  }
  .runs-note {
    margin-top: 10px;
  }
  .runs-form {
    display: grid;
    gap: 8px;
  }
  .runs-check {
    display: flex;
    gap: 8px;
    align-items: center;
    color: var(--text);
  }
  .runs-actions {
    display: flex;
    justify-content: flex-start;
    margin-top: 4px;
  }
  /* Label-left form rows from tablet width up, the Servarr settings layout. */
  @media (min-width: 769px) {
    .runs-form {
      grid-template-columns: 11rem minmax(0, 1fr);
      align-items: center;
      column-gap: 16px;
    }
    .runs-form > label:not(.runs-check) {
      color: var(--muted);
    }
    .runs-form > .runs-check,
    .runs-form > .runs-actions {
      grid-column: 2;
    }
  }
  .runs-table {
    min-width: 760px;
  }
  .runs-schedule {
    margin-top: 8px;
  }
</style>
