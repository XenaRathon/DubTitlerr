<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError } from '../lib/api.js';
  import {
    buildQuery,
    createLatest,
    formatAge,
    pageWindow,
    summarizeCounts,
    warmingRetryDelay,
  } from '../lib/dashboard.js';
  import StatusBadge, { STAGE_STATUS } from '../lib/StatusBadge.svelte';

  // Plain words for the pipeline stages (review_status.STAGES); an unknown stage shows as sent.
  const STAGE_LABELS: Record<string, string> = {
    transcribed: 'Transcribed',
    repaired: 'Repaired',
    muxed: 'Subtitles added',
    failed: 'Failed',
    stale: 'Out of date',
    'pending-review': 'Needs review',
  };
  const stageLabel = (stage: string) => STAGE_LABELS[stage] ?? stage;

  // The per-episode strip: how far along transcribe → repair → mux a stage proves the episode got.
  // Failed and stale say nothing about how far it got, so they show no strip rather than a guess. Pending review
  // proves a repair ran but not whether the mux did (review_status checks pending before muxed), so mux stays unconfirmed.
  const STEPS = ['transcribed', 'repaired', 'muxed'] as const;
  const STEPS_REACHED: Record<string, number> = {
    transcribed: 1,
    repaired: 2,
    'pending-review': 2,
    muxed: 3,
  };
  function describeSteps(reached: number) {
    const name = (s: string) => stageLabel(s).toLowerCase();
    const done = STEPS.slice(0, reached).map(name).join(', ');
    const left = STEPS.slice(reached).map(name);
    return left.length ? `${done}; not confirmed: ${left.join(', ')}` : done;
  }

  interface EpisodeStatus {
    show: string;
    season: string;
    episode: string;
    stem: string;
    stage: string;
    last_outcome: string;
    repair_model: string | null;
    text_version: number | null;
    pending_review_count: number;
    updated_at: number | null;
  }

  interface StatusHeader {
    builder_heartbeat_age_s: number | null;
    last_sweep_end: number | null;
    current_show: string | null;
    cache_age_s: number | null;
    counts_per_stage: Record<string, number>;
    total: number;
    page: number;
    limit: number;
    pages: number;
  }

  // The same authenticated fetch wrapper App.svelte uses: GET when body is absent, POST otherwise.
  let { api }: { api: (path: string, body?: object) => Promise<any> } = $props();

  const LIMIT = 50;
  const REFRESH_MS = 30000;

  let showFilter = $state(''); // what is typed in the box
  let appliedShow = ''; // what the operator applied; only this reaches the server, so a timer refresh never uses half-typed text
  let page = $state(1);
  let header = $state<StatusHeader | null>(null);
  let episodes = $state<EpisodeStatus[]>([]);
  let loading = $state(false);
  let status = $state('');
  let errorMsg = $state('');
  let warming = $state(false);
  let retryTimer = 0;
  let refreshTimer = 0;
  let retries = 0;
  let waitingForTab = false;
  let gaveUp = false; // retries used up: no timer refresh until the operator asks again
  const latest = createLatest();

  const counts = $derived(summarizeCounts(header ?? {}));
  const pages = $derived(header?.pages ?? 1);
  const window_ = $derived(pageWindow(page, pages));

  function formatTime(ts: number | null) {
    return typeof ts === 'number' && Number.isFinite(ts) ? new Date(ts * 1000).toLocaleString() : '—';
  }
  // "3 min ago" with the full time on hover; a time in the future (clock skew) falls back to the full time.
  function formatAgo(ts: number | null) {
    if (typeof ts !== 'number' || !Number.isFinite(ts)) return '—';
    const age = formatAge(Date.now() / 1000 - ts);
    return age === 'unknown' ? formatTime(ts) : `${age} ago`;
  }

  // `auto` marks a retry or timer refresh; a click, a filter or a page change starts the retry budget over.
  async function load(auto = false) {
    if (!auto) {
      retries = 0;
      gaveUp = false;
    }
    const wasWarming = warming; // the "warming up" line must be replaced once the data finally arrives
    const mine = latest.begin(); // an older, slower response must never overwrite this one
    loading = true;
    errorMsg = '';
    window.clearTimeout(retryTimer);
    retryTimer = 0;
    try {
      const data = (await api('/api/status' + buildQuery({ show: appliedShow, page, limit: LIMIT }))) as {
        header: StatusHeader;
        episodes: EpisodeStatus[];
      };
      if (!latest.isCurrent(mine)) return;
      header = data.header;
      episodes = data.episodes;
      page = data.header.page;
      warming = false;
      retries = 0;
      // Only a load the operator asked for speaks: a timer refresh must not re-announce itself to a screen reader.
      if (!auto || wasWarming)
        status = `Updated. ${data.header.total} episodes, page ${data.header.page} of ${data.header.pages}.`;
    } catch (exc) {
      if (!latest.isCurrent(mine)) return;
      if (exc instanceof ApiError && exc.status === 503) {
        const delay = warmingRetryDelay(retries);
        if (delay === null) {
          warming = false;
          gaveUp = true;
          errorMsg = 'The library index is still warming up. Use Refresh to try again.';
        } else {
          warming = true;
          status = 'Library index is warming up, retrying.';
          retries++;
          retryTimer = window.setTimeout(retryWhenVisible, delay);
        }
      } else {
        warming = false;
        errorMsg = exc instanceof Error ? exc.message : 'Request failed. Please try again.';
      }
    } finally {
      if (latest.isCurrent(mine)) loading = false;
    }
  }

  // A hidden tab pauses the retry loop; coming back to the tab resumes it.
  function retryWhenVisible() {
    if (document.hidden) waitingForTab = true;
    else void load(true);
  }
  function onVisibility() {
    if (!document.hidden && waitingForTab) {
      waitingForTab = false;
      void load(true);
    }
  }

  function goto(next: number) {
    page = next;
    void load();
  }

  function applyFilter() {
    appliedShow = showFilter;
    page = 1;
    void load();
  }

  onMount(() => {
    void load();
    refreshTimer = window.setInterval(() => {
      if (!document.hidden && !warming && !gaveUp) void load(true);
    }, REFRESH_MS);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.clearInterval(refreshTimer);
      window.clearTimeout(retryTimer);
      document.removeEventListener('visibilitychange', onVisibility);
      latest.cancel(); // a response that lands after the page is gone applies nothing
    };
  });
</script>

<section aria-label="Status dashboard">
  <header class="page-header">
    <h1 tabindex="-1">Pipeline status</h1>
    <button class="secondary" type="button" disabled={loading} onclick={() => void load()}>Refresh</button>
  </header>
  <p class="page-sub" role="status" aria-live="polite">
    {warming ? 'Library index is warming up, retrying.' : status}
  </p>

  {#if errorMsg}<p class="notice failure" role="alert">{errorMsg}</p>{/if}

  <section class="stats dashboard-stats" aria-label="Builder heartbeat">
    <article>
      <div>
        <span>Builder heartbeat</span><strong>{formatAge(header?.builder_heartbeat_age_s ?? null)}</strong
        ><small>Time since the builder last checked in</small>
      </div>
    </article>
    <article>
      <div>
        <span>Last sweep end</span><strong title={formatTime(header?.last_sweep_end ?? null)}
          >{formatAgo(header?.last_sweep_end ?? null)}</strong
        ><small>When the last sweep finished</small>
      </div>
    </article>
    <article>
      <div>
        <span>Index cache age</span><strong>{formatAge(header?.cache_age_s ?? null)}</strong><small
          >How old the library index is</small
        >
      </div>
    </article>
    <article>
      <div>
        <span>Current show</span><strong class:unset={!header?.current_show}
          >{header?.current_show || 'not reported'}</strong
        ><small>What the builder is working on</small>
      </div>
    </article>
  </section>

  <section aria-label="Episodes per stage">
    <div class="dashboard-counts">
      {#each counts as { stage, count } (stage)}<StatusBadge
          status={STAGE_STATUS[stage]}
          label={`${stageLabel(stage)}: ${count}`}
        />{/each}
    </div>
    <small class="dashboard-scope">Counts cover the current page only.</small>
  </section>

  <form
    class="dashboard-filter"
    onsubmit={(e) => {
      e.preventDefault();
      applyFilter();
    }}
  >
    <label for="dashboard-show">Show</label>
    <input
      id="dashboard-show"
      bind:value={showFilter}
      placeholder="Filter by show…"
      autocomplete="off"
      spellcheck="false"
    />
    <button class="secondary" type="submit" disabled={loading}>Apply filter</button>
  </form>

  {#if loading && !episodes.length}
    <p class="page-sub">Loading episode status…</p>
  {:else}
    <!-- Ten columns do not fit a phone: the table scrolls inside this region (focusable, so the keyboard can too;
         axe's scrollable-region-focusable rule requires it). -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="table-scroll" role="region" aria-label="Episode status" tabindex="0">
      <table class="data-table dashboard-table">
        <thead>
          <tr>
            <th scope="col">Show</th>
            <th scope="col">Season</th>
            <th scope="col">Episode</th>
            <th scope="col">Stage</th>
            <th scope="col">Progress</th>
            <th scope="col">Last outcome</th>
            <th scope="col">Repair model</th>
            <th scope="col">Text version</th>
            <th scope="col">Pending review</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {#each episodes as ep (ep.stem)}
            {@const reached = STEPS_REACHED[ep.stage]}
            <tr>
              <td>{ep.show}</td>
              <td>{ep.season}</td>
              <td>{ep.episode}</td>
              <td><StatusBadge status={STAGE_STATUS[ep.stage]} label={stageLabel(ep.stage)} /></td>
              <td>
                {#if reached === undefined}
                  <span class="unset">—</span>
                {:else}
                  <span class="stage-strip" role="img" aria-label={describeSteps(reached)}>
                    {#each STEPS as step, i (step)}<span class="step" class:reached={i < reached}
                      ></span>{/each}
                  </span>
                {/if}
              </td>
              <td>{ep.last_outcome}</td>
              <td>{ep.repair_model ?? '—'}</td>
              <td class="num">{ep.text_version ?? '—'}</td>
              <td class="num">{ep.pending_review_count}</td>
              <td title={formatTime(ep.updated_at)}>{formatAgo(ep.updated_at)}</td>
            </tr>
          {:else}
            <tr><td class="empty-row" colspan="10">No episodes on this page.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>

    <nav class="dashboard-pages" aria-label="Episode pages">
      <button
        class="secondary"
        type="button"
        aria-label="Previous page"
        disabled={loading || page <= 1}
        onclick={() => goto(page - 1)}>Previous</button
      >
      {#each window_ as p (p)}<button
          class="secondary"
          type="button"
          aria-label={`Go to page ${p}`}
          aria-current={p === page ? 'page' : undefined}
          disabled={loading || p === page}
          onclick={() => goto(p)}>{p}</button
        >{/each}
      <button
        class="secondary"
        type="button"
        aria-label="Next page"
        disabled={loading || page >= pages}
        onclick={() => goto(page + 1)}>Next</button
      >
    </nav>
  {/if}
</section>

<style>
  .dashboard-stats strong.unset,
  .unset {
    color: var(--muted);
  }
  .dashboard-counts {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 6px;
  }
  .dashboard-scope {
    color: var(--muted);
  }
  .dashboard-filter {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin: 16px 0 12px;
  }
  .dashboard-filter label {
    color: var(--muted);
  }
  .dashboard-table {
    min-width: 860px;
  }
  .num {
    text-align: right;
  }
  .stage-strip {
    display: inline-flex;
    gap: 2px;
    vertical-align: middle;
  }
  .step {
    width: 18px;
    height: 6px;
    border-radius: 1px;
    background: var(--surface);
    border: 1px solid var(--border);
  }
  .step.reached {
    background: var(--ok);
    border-color: var(--ok);
  }
  .dashboard-pages {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 12px;
  }
  /* The current page reads as selected, not merely disabled. */
  .dashboard-pages [aria-current='page'] {
    border-color: var(--accent);
    color: var(--text);
  }
</style>
