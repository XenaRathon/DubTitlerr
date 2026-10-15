<script lang="ts">
  import { onMount, tick, untrack } from 'svelte';
  import {
    BookOpen,
    Check,
    ChevronLeft,
    ChevronRight,
    CircleHelp,
    ClipboardCheck,
    Filter,
    GitCompareArrows,
    Inbox,
    LoaderCircle,
    LockKeyhole,
    Menu,
    Play,
    RefreshCw,
    Save,
    Search,
    ShieldCheck,
    Sparkles,
    X,
  } from '@lucide/svelte';
  import Sidebar from './lib/Sidebar.svelte';
  import StatusBadge from './lib/StatusBadge.svelte';
  import Dashboard from './pages/Dashboard.svelte';
  import Glossary from './pages/Glossary.svelte';
  import Runs from './pages/Runs.svelte';
  import Settings from './pages/Settings.svelte';
  import UnsavedDialog from './lib/UnsavedDialog.svelte';
  import { ApiError } from './lib/api.js';
  import Login from './pages/Login.svelte';
  import Setup from './pages/Setup.svelte';
  import AccountMenu from './lib/AccountMenu.svelte';
  import { apiFetch, logout as endSession, me as fetchMe } from './lib/session.js';
  import { canonicalHash, hashFor, parseHash, parseSettingsCategory } from './lib/route.js';
  import { isSaveShortcut } from './lib/settingsModel.js';
  import { EPISODE_SORTS, LINE_SORTS, readSortPref, sortEpisodes, writeSortPref } from './lib/episodeSort.js';
  import type { Draft, Entry, Episode, SaveResult, Shared, Verdict } from './types';
  import { blank, diffParts, nextOpenIndex, riskLabels, timecode, verdictLabels } from './review';

  type View = 'inbox' | 'shared' | 'dashboard' | 'glossary' | 'runs' | 'settings';
  const VIEW_TITLES: Record<View, string> = {
    inbox: 'Review inbox',
    shared: 'Shared lines',
    dashboard: 'Dashboard',
    glossary: 'Glossary',
    runs: 'Runs',
    settings: 'Settings',
  };
  // The location hash names the view, so a deep link and the back button both work; a deep link taken while
  // signed out keeps its hash because nothing below rewrites it until the operator navigates.
  const initialView = parseHash(typeof location === 'undefined' ? '' : location.hash);
  let view = $state<View>(initialView);
  type Account = { state: 'loading' | 'setup' | 'login' | 'in'; username: string; role: string };
  let account = $state<Account>({ state: 'loading', username: '', role: '' });
  let accountsOk = $state(true);
  // The settings category page ('' is the card grid); it rides in the hash as #/settings/<category>.
  let settingsCategory = $state(parseSettingsCategory(typeof location === 'undefined' ? '' : location.hash));
  let settingsDirty = $state(false); // Settings.svelte reports unsaved edits through bind:dirty
  let settingsPage = $state<{ save: () => Promise<void> } | undefined>();
  // A move away from an edited settings page waits here until the operator answers the "Unsaved changes" dialog.
  let unsavedGo = $state<(() => void) | null>(null);
  let authenticated = $state(false);
  let loading = $state(false);
  let saving = $state(false);
  let message = $state('');
  let error = $state('');
  let episodes = $state<Episode[]>([]);
  let selected = $state<Episode | null>(null);
  let entries = $state<Entry[]>([]);
  let shared = $state<Shared[]>([]);
  let drafts = $state<Record<string, Draft>>({});
  let activeId = $state('');
  let query = $state('');
  let lineQuery = $state('');
  let show = $state('all');
  let showRefused = $state(false);
  let risk = $state('all');
  // Both sort choices are remembered per browser; a stored value this build does not know falls back to the default.
  const EPISODE_SORT_KEY = 'dubtitlerr_episode_sort';
  const LINE_SORT_KEY = 'dubtitlerr_line_sort';
  const storage = () => (typeof localStorage === 'undefined' ? undefined : localStorage);
  const storedLineSort = () => readSortPref(storage(), LINE_SORT_KEY, LINE_SORTS, 'risk');
  // A deep link into the shared view has no Time option, so it opens on risk as before.
  let order = $state<string>(initialView === 'shared' ? 'risk' : storedLineSort());
  let episodeOrder = $state<string>(readSortPref(storage(), EPISODE_SORT_KEY, EPISODE_SORTS, 'default'));
  let showHelp = $state(false);
  let mobileNav = $state(false);
  let health = $state('Unknown');
  let audioUrl = $state('');
  let audioLoading = $state(false);
  let audioError = $state('');
  let occurrence = $state(0);
  let player = $state<HTMLAudioElement>();
  let correction = $state<HTMLTextAreaElement>();
  let helpDialog = $state<HTMLDialogElement>();
  $effect(() => {
    if (showHelp && helpDialog && !helpDialog.open) helpDialog.showModal();
  });
  let audioRequest = 0;
  let lastEvidenceId = '';
  // Filters can change the active question without clicking Next. Never keep another line's clip on screen.
  $effect(() => {
    const id = current?.id ?? '';
    if (id !== lastEvidenceId) {
      untrack(stopAudio);
      lastEvidenceId = id;
    }
  });

  const staged = $derived(Object.keys(drafts).length);
  const admitted = $derived(episodes.reduce((n, ep) => n + ep.admitted, 0));
  const refused = $derived(episodes.reduce((n, ep) => n + ep.refused, 0));
  const shows = $derived([...new Set(episodes.map((ep) => ep.show))].sort());
  // Episodes with at least one repair waiting for a person: the number the sidebar badge and the inbox agree on.
  const toReview = $derived(episodes.filter((ep) => ep.admitted > 0).length);
  const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
  // The muted status line under the page title.
  const queueSummary = $derived(
    view === 'shared'
      ? `${plural(shared.length, 'repeated change')} across episodes. One verdict settles every copy.`
      : `${plural(admitted, 'repair')} in ${plural(toReview, 'episode')} need a decision.` +
          (refused
            ? ` ${plural(refused, 'other repair')} turned down by the safety check kept the original text.`
            : ''),
  );
  const filteredEpisodes = $derived(
    sortEpisodes(
      episodes.filter(
        (ep) =>
          (showRefused || ep.admitted > 0) &&
          (show === 'all' || ep.show === show) &&
          `${ep.show} ${ep.name} ${ep.season}`.toLowerCase().includes(query.toLowerCase()),
      ),
      episodeOrder,
    ),
  );
  const visible = $derived.by(() => {
    const rows: (Entry | Shared)[] = view === 'shared' ? shared : entries;
    return rows
      .filter(
        (e) =>
          (risk === 'all' || e.risk === risk) &&
          `${e.original_text} ${e.proposed_text}`.toLowerCase().includes(lineQuery.toLowerCase()),
      )
      .slice()
      .sort((a, b) => {
        if (order === 'time' && 'starts' in a && 'starts' in b)
          return (a.starts[0] ?? Infinity) - (b.starts[0] ?? Infinity);
        if (order === 'repeated' && 'episodes' in a && 'episodes' in b) return b.episodes - a.episodes;
        const stage = (e: Entry | Shared) => ('stage' in e && e.stage !== 'repair_applied' ? 1 : 0);
        const ranks = { words: 0, substitution: 1, punctuation: 2 };
        return stage(a) - stage(b) || ranks[a.risk] - ranks[b.risk];
      });
  });
  const current = $derived(visible.find((e) => e.id === activeId) ?? visible[0]);
  const activeIndex = $derived(current ? visible.findIndex((e) => e.id === current.id) : -1);
  const draft = $derived(current ? drafts[current.id] : undefined);
  const remaining = $derived(visible.filter((e) => !drafts[e.id]).length);

  // `extra` carries per-call headers; they go in the request headers, never in the JSON body.
  // `method` defaults to POST with a body and GET without; PUT and body-less POST (reset) name theirs.
  async function api<T>(
    path: string,
    body?: object,
    extra?: Record<string, string>,
    method?: string,
  ): Promise<T> {
    const res = await apiFetch(path, {
      method: method ?? (body ? 'POST' : 'GET'),
      headers: { ...extra, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (res.status === 401) {
      authenticated = false;
      account = { state: 'login', username: '', role: '' };
      // Staged review choices live in this tab; glossary or run-form text does not survive the login panel.
      error =
        view === 'inbox' || view === 'shared'
          ? 'Your session ended. Sign in again. Your staged choices are still held in this tab.'
          : 'Your session ended. Sign in again; unsaved text on that page was not kept.';
      throw new Error(error);
    }
    const result = await res.json();
    // An ApiError keeps the HTTP status and body, so a page can tell a 409 from a 503 instead of matching message text.
    if (!res.ok || result.error)
      throw new ApiError(result.error || `Request failed (${res.status})`, res.status, result);
    return result as T;
  }
  // Runs.svelte and Settings.svelte call api(path, { method, body, headers }); adapt that to the wrapper above.
  const optionsApi = (
    path: string,
    options?: { method?: string; body?: object; headers?: Record<string, string> },
  ) => api<any>(path, options?.body, options?.headers, options?.method);
  function report(exc: unknown) {
    error = exc instanceof Error ? exc.message : 'Request failed. Please try again.';
  }
  async function loadIndex() {
    episodes = (await api<{ episodes: Episode[] }>('/api/episodes')).episodes;
  }
  // Called once a session exists (a restored one on page load, or a fresh sign-in or setup).
  async function enter(user: { username: string; role: string }) {
    account = { state: 'in', username: user.username, role: user.role };
    error = '';
    try {
      await loadIndex();
      authenticated = true;
      try {
        const res = await fetch('/healthz');
        const data = await res.json();
        health = data.ok ? 'Healthy' : 'Needs attention';
      } catch {
        health = 'Unknown';
      }
      if (view === 'shared') shared = (await api<{ pairs: Shared[] }>('/api/shared')).pairs;
      else if (selected) await loadEpisode(selected);
    } catch (exc) {
      report(exc);
    }
  }
  function stopAudio() {
    audioRequest++;
    player?.pause();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = '';
    audioError = '';
    audioLoading = false;
    occurrence = 0;
  }
  // The glossary page reports unsaved add-form/edit-row text through bind:dirty.
  let glossaryDirty = $state(false);
  function discardOK() {
    if (view === 'glossary' && glossaryDirty)
      return window.confirm('Discard your unsaved glossary edits? Nothing has been saved yet.');
    return !staged || window.confirm('Discard your unsaved review choices? Nothing has been saved yet.');
  }
  // Sidebar clicks go through the hash so the browser history records them; onhashchange does the switch. The discard
  // prompt comes BEFORE the hash changes, so declining leaves no history entry behind; `agreedHash` tells onHashChange
  // not to ask a second time.
  let agreedHash = '';
  function navigate(next: View) {
    if (next === view) {
      if (next === 'settings' && settingsCategory) {
        const toGrid = () => (location.hash = '#/settings'); // the sidebar item returns to the card grid
        if (settingsDirty) askDiscard(toGrid);
        else toGrid();
      }
      closeDrawer(true);
      return;
    }
    mobileNav = false;
    if (saving || loading) return;
    if (view === 'settings' && settingsDirty) {
      askDiscard(() => go(next));
      return;
    }
    if (!discardOK()) return;
    go(next);
  }
  function go(next: View) {
    agreedHash = hashFor(next);
    location.hash = agreedHash;
  }
  function askDiscard(proceed: () => void) {
    unsavedGo = proceed;
  }
  // Back/forward and typed hashes land here. Declining the discard prompt puts the hash back for the view we stay on.
  async function onHashChange() {
    const next = parseHash(location.hash);
    const target = canonicalHash(location.hash);
    const agreed = agreedHash === target;
    agreedHash = '';
    if (view === 'settings' && settingsDirty && !agreed && target !== currentHash()) {
      // A typed hash, a settings link or Back while the page holds edits: put the address back and ask first.
      history.replaceState(null, '', currentHash());
      askDiscard(() => {
        agreedHash = target;
        location.hash = target;
      });
      return;
    }
    if (next === view) {
      const category = parseSettingsCategory(location.hash);
      if (view === 'settings' && category !== settingsCategory) {
        settingsCategory = category;
        void focusHeading(); // a new category page: its title takes focus, as a new view's does
      }
      if (location.hash !== target && location.hash !== '') history.replaceState(null, '', target);
      return;
    }
    if (saving || loading || (!agreed && !discardOK())) {
      history.replaceState(null, '', currentHash());
      return;
    }
    await switchView(next);
    if (location.hash !== target) history.replaceState(null, '', target); // '#/glossary?x=1' -> '#/glossary'
  }
  // The canonical hash of the page that is open, for putting the address bar back when a move is declined.
  const currentHash = () =>
    view === 'settings' ? canonicalHash('#/settings/' + settingsCategory) : hashFor(view);
  // Drawer: closing it returns focus to the toggle when the operator did not pick a page.
  let toggleBtn = $state<HTMLButtonElement>();
  let narrow = $state(false);
  function closeDrawer(refocus: boolean) {
    mobileNav = false;
    if (refocus) void tick().then(() => toggleBtn?.focus());
  }
  // The new page's title takes focus, so a keyboard or screen-reader user knows the page changed.
  async function focusHeading() {
    await tick();
    document.querySelector<HTMLElement>('main h1')?.focus();
  }
  function skipToContent(e: Event) {
    e.preventDefault(); // a plain #main href would be read as a route by the hash router
    document.getElementById('main')?.focus();
  }
  async function switchView(next: View) {
    if (next === 'settings') settingsCategory = parseSettingsCategory(location.hash);
    if (!authenticated) {
      view = next; // signed out: just remember the requested view; login() loads whatever it needs
      return;
    }
    glossaryDirty = false; // the glossary page is about to unmount; the caller already confirmed the discard
    settingsDirty = false; // likewise the settings page
    drafts = {};
    stopAudio();
    view = next;
    void focusHeading();
    activeId = '';
    lineQuery = '';
    risk = 'all';
    mobileNav = false;
    message = '';
    error = '';
    if (next === 'shared') {
      loading = true;
      try {
        shared = (await api<{ pairs: Shared[] }>('/api/shared')).pairs;
        order = 'repeated';
      } catch (exc) {
        report(exc);
      } finally {
        loading = false;
      }
    } else if (next === 'inbox') {
      order = storedLineSort();
      loading = true;
      try {
        await loadIndex();
        if (selected) await loadEpisode(selected);
      } catch (exc) {
        report(exc);
      } finally {
        loading = false;
      }
    }
  }
  async function loadEpisode(ep: Episode) {
    const data = await api<{ entries: Entry[]; name: string }>(
      '/api/episode?stem=' + encodeURIComponent(ep.stem),
    );
    entries = data.entries;
    selected = ep;
    activeId = entries[0]?.id ?? '';
  }
  async function selectEpisode(ep: Episode) {
    if (saving || loading || !discardOK()) return;
    loading = true;
    error = '';
    message = '';
    drafts = {};
    stopAudio();
    try {
      await loadEpisode(ep);
      order = storedLineSort();
      lineQuery = '';
      risk = 'all';
    } catch (exc) {
      report(exc);
    } finally {
      loading = false;
    }
  }
  function activate(id: string) {
    if (id !== current?.id) stopAudio();
    activeId = id;
  }
  function move(delta: number) {
    if (visible.length) activate(visible[(activeIndex + delta + visible.length) % visible.length].id);
  }
  function choose(verdict: Verdict) {
    if (!current || saving || !current.offered.includes(verdict)) return;
    drafts[current.id] = {
      verdict,
      text: drafts[current.id]?.text ?? current.proposed_text ?? '',
      note: drafts[current.id]?.note ?? '',
    };
    if (verdict === 'correct') void tick().then(() => correction?.focus());
    else {
      // Triage flow: a staged verdict moves on to the next line with no choice yet. Stays put at the end.
      const ids = visible.map((e) => e.id);
      const next = nextOpenIndex(ids, (id) => !!drafts[id], activeIndex);
      if (next !== activeIndex) activate(ids[next]);
    }
  }
  function editDraft(field: 'text' | 'note', value: string) {
    if (current && drafts[current.id]) drafts[current.id][field] = value;
  }
  function clearChoice() {
    if (current && !saving) delete drafts[current.id];
  }
  async function save() {
    if (!staged || saving || loading) return;
    const rows = view === 'shared' ? shared : entries;
    const wanted = rows.filter((e) => drafts[e.id]);
    if (wanted.some((e) => drafts[e.id].verdict === 'correct' && blank(drafts[e.id].text))) {
      error = 'A correction needs visible text. Fill it in or clear that choice.';
      return;
    }
    if (
      wanted.some((e) => drafts[e.id].verdict === 'force') &&
      !window.confirm(
        'Override the safety check for the selected lines? Listen to the audio before saving an override.',
      )
    )
      return;
    saving = true;
    error = '';
    message = '';
    try {
      const decisions = wanted.map((e) => ({
        ...drafts[e.id],
        id: e.id,
        ...('index' in e ? { index: e.index } : {}),
      }));
      const result = await api<SaveResult>(
        view === 'shared' ? '/api/shared' : '/api/decide',
        view === 'shared' ? { decisions } : { stem: selected?.stem, decisions },
      );
      // Refresh from the authoritative store. On partial success, only questions that disappeared lose their drafts.
      if (view === 'shared') shared = (await api<{ pairs: Shared[] }>('/api/shared')).pairs;
      else if (selected) await loadEpisode(selected);
      const live = new Set((view === 'shared' ? shared : entries).map((e) => e.id));
      for (const id of Object.keys(drafts)) if (!live.has(id)) delete drafts[id];
      message = `${result.saved} choice${result.saved === 1 ? '' : 's'} saved. ${result.warning ?? 'Apply is a separate step; media was not rewritten.'}`;
      if (result.errors?.length) error = result.errors.map((e) => e.error).join(' · ');
      stopAudio();
      await loadIndex();
    } catch (exc) {
      report(exc);
    } finally {
      saving = false;
    }
  }
  async function refresh() {
    if (saving || loading || !discardOK()) return;
    drafts = {};
    loading = true;
    error = '';
    stopAudio();
    try {
      await loadIndex();
      if (view === 'shared') shared = (await api<{ pairs: Shared[] }>('/api/shared')).pairs;
      else if (selected) await loadEpisode(selected);
      message = 'Review data refreshed. New episodes appear after server discovery completes.';
    } catch (exc) {
      report(exc);
    } finally {
      loading = false;
    }
  }
  async function apply() {
    if (!selected || saving || loading) return;
    if (staged) {
      error = 'Save or clear your staged choices before applying saved decisions.';
      return;
    }
    if (
      !window.confirm(
        'Apply saved decisions to this episode? This rebuilds subtitles and queues a remux of the media file.',
      )
    )
      return;
    saving = true;
    error = '';
    try {
      const result = await api<{ changed: number }>('/api/apply', { stem: selected.stem });
      message = result.changed
        ? `${result.changed} matching card(s); subtitles rebuilt and remux queued.`
        : 'No matching saved decisions to apply.';
    } catch (exc) {
      report(exc);
    } finally {
      saving = false;
    }
  }
  async function playClip() {
    if (!current || !('index' in current) || !selected) return;
    if (audioUrl && player) {
      if (player.paused) {
        player.currentTime = 0;
        void player.play().catch(report);
      } else player.pause();
      return;
    }
    audioLoading = true;
    audioError = '';
    const requestId = ++audioRequest;
    try {
      const params = new URLSearchParams({
        stem: selected.stem,
        index: String(current.index),
        id: current.id,
        occurrence: String(occurrence),
      });
      const res = await apiFetch('/api/audio?' + params);
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Audio preview failed');
      }
      const blob = await res.blob();
      if (requestId !== audioRequest) return;
      audioUrl = URL.createObjectURL(blob);
      await tick();
      await player?.play();
    } catch (exc) {
      if (requestId === audioRequest) audioError = exc instanceof Error ? exc.message : 'Audio unavailable';
    } finally {
      if (requestId === audioRequest) audioLoading = false;
    }
  }
  function keydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && mobileNav) {
      closeDrawer(true);
      return;
    }
    if (view === 'settings' && isSaveShortcut(e) && authenticated) {
      e.preventDefault(); // Ctrl+S / Cmd+S saves the settings page, never the browser's "save page as"
      void settingsPage?.save();
      return;
    }
    if (view !== 'inbox' && view !== 'shared') return; // the review shortcuts and Ctrl+S belong to the review views
    const input =
      e.target instanceof HTMLElement &&
      (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A', 'AUDIO'].includes(e.target.tagName) ||
        e.target.isContentEditable);
    if ((e.ctrlKey || e.metaKey) && e.key === 's' && authenticated) {
      e.preventDefault();
      void save();
      return;
    }
    if (input || showHelp || !authenticated || saving || loading) return;
    const key = e.key.toLowerCase();
    if (key === 'j' || key === 'arrowdown') {
      e.preventDefault();
      move(1);
    }
    if (key === 'k' || key === 'arrowup') {
      e.preventDefault();
      move(-1);
    }
    if (key === 'a') choose('accept');
    if (key === 'r') choose('reject');
    if (key === 'c') choose('correct');
    if (key === 'escape') clearChoice();
    if (key === ' ') {
      e.preventDefault();
      void playClip();
    }
    if (key === '?') showHelp = !showHelp;
  }
  function beforeUnload(e: BeforeUnloadEvent) {
    if (staged || (view === 'glossary' && glossaryDirty) || (view === 'settings' && settingsDirty)) {
      e.preventDefault();
      e.returnValue = '';
    }
  }
  async function logout() {
    if (saving || loading) return;
    if (view === 'settings' && settingsDirty) {
      askDiscard(() => void logout()); // Discard clears settingsDirty, so the second call signs out
      return;
    }
    if (!discardOK()) return;
    try {
      await endSession();
    } catch {
      /* the next request answers 401 and the page falls back to the sign-in form */
    }
    glossaryDirty = false;
    stopAudio();
    drafts = {};
    entries = [];
    shared = [];
    episodes = [];
    selected = null;
    authenticated = false;
    account = { state: 'login', username: '', role: '' };
    message = '';
    error = '';
  }
  onMount(() => {
    if (location.hash !== '' && location.hash !== canonicalHash(location.hash))
      history.replaceState(null, '', canonicalHash(location.hash));
    void (async () => {
      try {
        const who = await fetchMe();
        if (who.state === 'in') await enter(who);
        else account = { state: who.state, username: '', role: '' };
        if (who.state === 'login') {
          const mode = await fetch('/api/auth-mode').then((r) => r.json());
          accountsOk = mode.accounts_ok !== false;
        }
      } catch {
        account = { state: 'login', username: '', role: '' };
      }
    })();
    const narrowQuery = window.matchMedia('(max-width: 768px)');
    narrow = narrowQuery.matches;
    const syncNarrow = (e: MediaQueryListEvent) => {
      narrow = e.matches;
      if (!narrow) mobileNav = false; // a drawer left open must not freeze the page after the window widens
    };
    narrowQuery.addEventListener('change', syncNarrow);
    return () => {
      narrowQuery.removeEventListener('change', syncNarrow);
      stopAudio();
    };
  });
</script>

<svelte:window onkeydown={keydown} onbeforeunload={beforeUnload} onhashchange={onHashChange} />

<a class="skip-link" href="#main" onclick={skipToContent}>Skip to content</a>
<div class="app-shell">
  <Sidebar
    {view}
    {authenticated}
    busy={saving || loading}
    count={toReview}
    open={mobileNav}
    {narrow}
    {settingsCategory}
    onnavigate={navigate}
    onpick={() => closeDrawer(false)}
  />

  <div class="main-shell" inert={mobileNav && narrow}>
    <header class="topbar">
      <div class="breadcrumb">
        <button
          class="icon-button mobile-menu"
          aria-label="Toggle navigation"
          bind:this={toggleBtn}
          onclick={() => (mobileNav = !mobileNav)}><Menu size={20} /></button
        >{#if authenticated}<span>Workspace</span><ChevronRight size={14} /><strong
            >{VIEW_TITLES[view]}</strong
          >{:else}<strong>Sign in</strong>{/if}
      </div>
      <div class="topbar-actions">
        <span class="health"
          ><span class:warning={health !== 'Healthy'} class="status-dot"></span>{authenticated
            ? health
            : 'Sign in required'}</span
        >{#if view === 'inbox' || view === 'shared'}<button
            class="icon-button"
            aria-label="Keyboard shortcuts"
            onclick={() => (showHelp = !showHelp)}><CircleHelp size={19} /></button
          >{/if}{#if authenticated}<AccountMenu
            username={account.username}
            role={account.role}
            onlogout={logout}
            disabled={saving}
          />{/if}
      </div>
    </header>

    <main id="main" tabindex="-1">
      {#if account.state === 'loading'}
        <p class="page-sub" role="status">Checking your session…</p>
      {:else if account.state === 'setup'}
        <Setup
          onsignedin={enter}
          onalreadysetup={(message) => {
            account = { state: 'login', username: '', role: '' };
            error = message;
          }}
        />
      {:else if !authenticated}
        <Login
          onsignedin={enter}
          notice={error ||
            (accountsOk
              ? ''
              : 'The accounts file cannot be read. An administrator can recover with: python3 review_users.py reset-admin <name>')}
        />
      {:else if view === 'glossary'}
        <Glossary {api} bind:dirty={glossaryDirty} />
      {:else if view === 'dashboard'}
        <Dashboard {api} />
      {:else if view === 'runs'}
        <Runs api={optionsApi} role={account.role} />
      {:else if view === 'settings'}
        <Settings
          bind:this={settingsPage}
          bind:dirty={settingsDirty}
          api={optionsApi}
          role={account.role}
          category={settingsCategory}
        />
      {:else}
        <header class="page-header">
          <h1 tabindex="-1">{view === 'shared' ? 'Shared lines' : 'Review inbox'}</h1>
          <button class="secondary" onclick={refresh} disabled={loading || saving}
            ><RefreshCw size={16} class={loading ? 'spin' : ''} />Refresh queue</button
          >
        </header>
        <p class="page-sub">{loading && !episodes.length ? 'Loading the review queue…' : queueSummary}</p>
        {#if message}<div class="notice success" role="status">
            <Check size={18} /><span>{message}</span><button
              class="icon-button"
              aria-label="Dismiss message"
              onclick={() => (message = '')}><X size={16} /></button
            >
          </div>{/if}
        {#if error}<div class="notice failure" role="alert">
            <ShieldCheck size={18} /><span>{error}</span><button
              class="icon-button"
              aria-label="Dismiss error"
              onclick={() => (error = '')}><X size={16} /></button
            >
          </div>{/if}

        <div class="workspace" class:shared-workspace={view === 'shared'}>
          {#if view === 'inbox'}
            <section class="episode-panel" aria-label="Episode inbox">
              <div class="panel-title">
                <h2>Episodes</h2>
                <span class="badge neutral">{filteredEpisodes.length}</span>
              </div>
              <label class="search-field"
                ><Search size={16} /><input
                  aria-label="Search episodes"
                  bind:value={query}
                  placeholder="Search shows or episodes…"
                /></label
              ><select class="show-select" aria-label="Filter by show" bind:value={show}
                ><option value="all">All shows</option>{#each shows as name (name)}<option value={name}
                    >{name}</option
                  >{/each}</select
              ><select
                class="show-select"
                aria-label="Sort episodes"
                bind:value={episodeOrder}
                onchange={() => writeSortPref(storage(), EPISODE_SORT_KEY, episodeOrder)}
                ><option value="default">Default order</option><option value="episode">Episode order</option
                ><option value="pending">Most repairs to check</option><option value="oldest"
                  >Oldest pending first</option
                ></select
              ><label class="toggle"
                ><input type="checkbox" bind:checked={showRefused} /><span
                  >Include episodes where every repair was turned down</span
                ></label
              >
              <div class="episode-list">
                {#each filteredEpisodes as ep (ep.stem)}<button
                    class="episode"
                    class:selected={selected?.stem === ep.stem}
                    onclick={() => selectEpisode(ep)}
                    disabled={saving || loading}
                    ><span class="episode-copy"
                      ><strong>{ep.name}</strong><small
                        >{ep.season}, {ep.admitted} to check{ep.refused
                          ? `, ${ep.refused} turned down`
                          : ''}</small
                      ></span
                    ><ChevronRight size={15} /></button
                  >{:else}<div class="empty-small">
                    <Inbox size={28} />
                    <p>No episodes match.</p>
                    <small>Try another filter, or include episodes where every repair was turned down.</small>
                  </div>{/each}
              </div>
              <div class="panel-footer">
                Episodes with repairs to check come first. Nothing is approved automatically.
              </div>
            </section>
          {/if}
          <section class="review-panel" aria-label="Review editor">
            <div class="review-title">
              <h2>
                {view === 'shared' ? 'Repeated changes' : (selected?.name ?? 'Choose an episode')}
              </h2>
              {#if view === 'inbox' && selected}<span class="badge neutral">{selected.season}</span>{/if}
            </div>
            {#if loading}<div class="empty-state">
                <LoaderCircle size={32} class="spin" />
                <h3>Loading review evidence…</h3>
                <p>Large media libraries can take a moment to discover.</p>
              </div>
            {:else if view === 'inbox' && !selected}<div class="empty-state">
                <GitCompareArrows size={32} aria-hidden="true" />
                <h3>No episode open</h3>
                <p>
                  Pick an episode from the list to compare its repairs with the original transcript, hear the
                  dub, and stage your verdicts.
                </p>
              </div>
            {:else}
              <div class="review-toolbar">
                <label class="search-field"
                  ><Search size={15} /><input
                    aria-label="Search review lines"
                    bind:value={lineQuery}
                    placeholder="Find a line…"
                  /></label
                ><label class="filter-control"
                  ><Filter size={14} /><select aria-label="Filter by risk" bind:value={risk}
                    ><option value="all">All changes</option><option value="words"
                      >Added / dropped words</option
                    ><option value="substitution">Substitutions</option><option value="punctuation"
                      >Punctuation / case</option
                    ></select
                  ></label
                ><select
                  aria-label="Sort review lines"
                  bind:value={order}
                  onchange={() => {
                    // The shared view's order is its own; only the inbox choice is remembered.
                    if (view === 'inbox') writeSortPref(storage(), LINE_SORT_KEY, order);
                  }}
                  ><option value="risk">Risk first</option>{#if view === 'shared'}<option value="repeated"
                      >Most repeated</option
                    >{:else}<option value="time">Time order</option>{/if}</select
                >
              </div>
              {#if current}
                <div class="line-strip" aria-label="Review lines">
                  {#each visible as e, i (e.id)}<button
                      class:active={current.id === e.id}
                      class:decided={!!drafts[e.id]}
                      onclick={() => activate(e.id)}
                      aria-label={`Review line ${i + 1}${drafts[e.id] ? ', staged' : ''}`}
                      aria-pressed={current.id === e.id}
                      >{#if drafts[e.id]}<Check size={13} />{:else}{i + 1}{/if}</button
                    >{/each}
                </div>
                <div class="evidence" data-testid="evidence">
                  <div class="card-meta">
                    <div>
                      <span class="badge neutral">{riskLabels[current.risk]}</span>{#if 'stage' in current}
                        <!-- An admitted repair waits for a verdict; a turned-down one already kept the original text. -->
                        {#if current.stage === 'repair_applied'}<StatusBadge
                            status="pending"
                            label="Repair to check"
                          />{:else}<StatusBadge
                            status="stale"
                            label="Turned down, original kept"
                          />{/if}{:else}<span class="badge neutral">{current.episodes} episodes</span>{/if}
                    </div>
                    <span class="muted">Line {activeIndex + 1} of {visible.length}</span>
                  </div>
                  {#if 'show' in current}<div class="shared-show">{current.show}</div>{/if}
                  {#if 'starts' in current && current.starts.length}<div class="audio-row">
                      <button class="listen" onclick={playClip} disabled={audioLoading}
                        >{#if audioLoading}<LoaderCircle size={17} class="spin" />{:else}<Play
                            size={17}
                          />{/if}{audioLoading ? 'Preparing clip…' : 'Listen to dub'}<kbd>Space</kbd></button
                      ><span class="timecode"
                        >{timecode(current.starts[occurrence] ?? current.starts[0])}</span
                      >{#if current.starts.length > 1}<select
                          aria-label="Audio occurrence"
                          value={occurrence}
                          onchange={(e) => {
                            stopAudio();
                            occurrence = Number(e.currentTarget.value);
                          }}
                          >{#each current.starts as start, i}<option value={i}
                              >Occurrence {i + 1} · {timecode(start)}</option
                            >{/each}</select
                        >{/if}<small>Up to 20s · English track</small>
                    </div>{/if}
                  {#if audioUrl}<audio
                      bind:this={player}
                      src={audioUrl}
                      controls
                      preload="none"
                      aria-label="English dub preview"
                    ></audio>{/if}{#if audioError}<p class="inline-error" role="alert">{audioError}</p>{/if}
                  {#if 'context' in current && current.context[occurrence]}<div class="context-line">
                      <span>Before</span>{current.context[occurrence].before.join(' ') || 'Start of episode'}
                    </div>{/if}
                  <div class="diff-grid">
                    <div class="diff-box original">
                      <div class="diff-label"><span class="tiny-dot"></span>Original transcript</div>
                      <p>
                        {#each diffParts(current.original_text, current.proposed_text, 'original') as part}{#if part.removed}<del
                              >{part.value}</del
                            >{:else}{part.value}{/if}{/each}
                      </p>
                    </div>
                    <div class="diff-box proposed">
                      <div class="diff-label"><Sparkles size={13} />Proposed repair</div>
                      <p>
                        {#each diffParts(current.original_text, current.proposed_text, 'proposed') as part}{#if part.added}<ins
                              >{part.value}</ins
                            >{:else}{part.value}{/if}{/each}
                      </p>
                    </div>
                  </div>
                  {#if 'context' in current && current.context[occurrence]}<div class="context-line">
                      <span>After</span>{current.context[occurrence].after.join(' ') || 'End of episode'}
                    </div>{/if}
                  {#if current.reference}<div class="reference">
                      <BookOpen size={16} />
                      <div>
                        <strong>Subtitle reference</strong>
                        <p>{current.reference}</p>
                        <small>A different translation, not the answer. Follow the dub audio.</small>
                      </div>
                    </div>{:else if 'permanent' in current && current.permanent}<div
                      class="reference no-reference"
                    >
                      <ShieldCheck size={17} />
                      <div>
                        <strong>No subtitle anchor</strong>
                        <p>Check the audio carefully. This change has no independent fansub reference.</p>
                      </div>
                    </div>{/if}
                  <div class="decision-heading">
                    <h3>Your verdict</h3>
                    <span>{draft ? 'Choice staged, not saved' : 'Nothing selected yet'}</span>
                  </div>
                  <div class="verdicts">
                    {#each current.offered as verdict (verdict)}<button
                        class:chosen={draft?.verdict === verdict}
                        class="verdict {verdict}"
                        onclick={() => choose(verdict)}
                        disabled={saving}
                        aria-pressed={draft?.verdict === verdict}
                        >{#if verdict === 'accept'}<Check
                            size={17}
                          />{:else if verdict === 'reject'}<ShieldCheck
                            size={17}
                          />{:else if verdict === 'force'}<LockKeyhole size={17} />{:else}<ClipboardCheck
                            size={17}
                          />{/if}{verdictLabels[verdict]}<kbd
                          >{verdict === 'accept'
                            ? 'A'
                            : verdict === 'reject'
                              ? 'R'
                              : verdict === 'correct'
                                ? 'C'
                                : '!'}</kbd
                        ></button
                      >{/each}
                  </div>
                  {#if draft?.verdict === 'correct'}<label class="correction-label" for="correction"
                      >Corrected subtitle</label
                    ><textarea
                      id="correction"
                      bind:this={correction}
                      value={draft.text}
                      oninput={(e) => editDraft('text', e.currentTarget.value)}
                      rows="3"
                      disabled={saving}
                      placeholder="Write what the dub actually says…"></textarea>{/if}
                  {#if draft}<div class="draft-tools">
                      {#if view === 'inbox'}<input
                          aria-label="Review note"
                          value={draft.note}
                          oninput={(e) => editDraft('note', e.currentTarget.value)}
                          placeholder="Optional note for the audit trail"
                          disabled={saving}
                        />{/if}<button class="text-button" onclick={clearChoice} disabled={saving}
                        ><X size={14} />Clear choice</button
                      >
                    </div>{/if}
                  <div class="card-navigation">
                    <button class="secondary" onclick={() => move(-1)} disabled={visible.length < 2}
                      ><ChevronLeft size={16} />Previous<kbd>K</kbd></button
                    ><span>{remaining} still to decide</span><button
                      class="secondary"
                      onclick={() => move(1)}
                      disabled={visible.length < 2}>Next line<kbd>J</kbd><ChevronRight size={16} /></button
                    >
                  </div>
                </div>
              {:else}<div class="empty-state">
                  <Check size={32} aria-hidden="true" />
                  <h3>{lineQuery || risk !== 'all' ? 'No matching changes' : 'This queue is clear.'}</h3>
                  <p>
                    {lineQuery || risk !== 'all'
                      ? 'Try another search or risk filter.'
                      : 'No undecided repairs remain in this view.'}
                  </p>
                </div>{/if}
            {/if}
            <footer class="save-bar">
              <div>
                <span class="save-count">{staged}</span>
                <div>
                  <strong>choices staged</strong><small
                    >Saving records verdicts. Applying queues a remux.</small
                  >
                </div>
              </div>
              <div>
                {#if view === 'inbox' && selected}<button
                    class="secondary apply-button"
                    onclick={apply}
                    disabled={saving || loading}>Apply saved decisions</button
                  >{/if}<button class="primary" onclick={save} disabled={!staged || saving || loading}
                  >{#if saving}<LoaderCircle size={16} class="spin" />{:else}<Save size={16} />{/if}{saving
                    ? 'Working…'
                    : `Save ${staged || ''} choice${staged === 1 ? '' : 's'}`}<kbd>⌘ / Ctrl S</kbd></button
                >
              </div>
            </footer>
          </section>
        </div>
        <div class="workspace-footnote">
          <ShieldCheck size={14} /><span
            >Human decisions are show-wide. Review the exact wording; a saved verdict may settle the same line
            in other episodes.</span
          ><button class="text-button" onclick={() => (showHelp = true)}
            >Keyboard shortcuts <kbd>?</kbd></button
          >
        </div>
      {/if}
    </main>
  </div>
</div>

{#if showHelp}<dialog
    bind:this={helpDialog}
    class="help-panel"
    aria-labelledby="help-title"
    onclose={() => (showHelp = false)}
  >
    <div class="panel-title">
      <h2 id="help-title">Keep your hands on the keyboard</h2>
      <button class="icon-button" aria-label="Close keyboard shortcuts" onclick={() => (showHelp = false)}
        ><X size={20} /></button
      >
    </div>
    <p>Shortcuts work outside form controls. Choices are staged, never auto-saved.</p>
    {#each [['J / ↓', 'Next line'], ['K / ↑', 'Previous line'], ['A', 'Keep repair (when offered)'], ['R', 'Keep original'], ['C', 'Write correction'], ['Space', 'Play / pause dub preview'], ['Escape', 'Clear current choice'], ['Ctrl / ⌘ S', 'Save staged choices']] as item (item[0])}<div
        class="shortcut-row"
      >
        <span>{item[1]}</span><kbd>{item[0]}</kbd>
      </div>{/each}<button class="primary" onclick={() => (showHelp = false)}>Back to review</button>
  </dialog>{/if}

{#if unsavedGo}
  <UnsavedDialog
    onstay={() => (unsavedGo = null)}
    ondiscard={() => {
      const proceed = unsavedGo;
      unsavedGo = null;
      settingsDirty = false;
      proceed?.();
    }}
  />
{/if}
