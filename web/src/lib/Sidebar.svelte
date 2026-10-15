<script lang="ts">
  import { tick } from 'svelte';
  import { SETTINGS_CATEGORIES, settingsHash } from './route.js';
  import {
    AudioLines,
    BookOpen,
    ExternalLink,
    Inbox,
    Layers,
    LayoutDashboard,
    ListChecks,
    Settings,
  } from '@lucide/svelte';

  type View = 'inbox' | 'shared' | 'dashboard' | 'glossary' | 'runs' | 'settings';

  let {
    view,
    authenticated,
    busy,
    count,
    open = false,
    narrow = false,
    settingsCategory = '',
    onnavigate,
    onpick,
  }: {
    view: View;
    authenticated: boolean;
    /** A load or save is in flight. The nav stays usable (App's navigate() refuses a switch mid-flight); this only marks it busy. */
    busy: boolean;
    /** Episodes waiting in the inbox; shown on the inbox item only. */
    count: number;
    /** The mobile menu is open (the sidebar slides in below 768px). */
    open?: boolean;
    /** Below 768px the sidebar is a slide-in drawer (App owns the media query, so the page and drawer agree). */
    narrow?: boolean;
    /** The settings category page that is open ('' for the card grid); the sidebar lists the categories under Settings. */
    settingsCategory?: string;
    onnavigate: (next: View) => void;
    /** A settings category link was followed; App closes the mobile drawer. */
    onpick?: () => void;
  } = $props();

  const ITEMS = [
    { key: 'inbox', label: 'Review inbox', icon: Inbox },
    { key: 'shared', label: 'Shared lines', icon: Layers },
    { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { key: 'glossary', label: 'Glossary', icon: BookOpen },
    { key: 'runs', label: 'Runs', icon: ListChecks },
    { key: 'settings', label: 'Settings', icon: Settings },
  ] as const;

  // A closed drawer sits off-screen, so it must not be reachable by Tab or a screen reader: `inert` removes it from both.
  // An opened one takes focus, so the keyboard user lands inside it.
  let navEl = $state<HTMLElement>();
  $effect(() => {
    if (open && narrow)
      void tick().then(() => navEl?.querySelector<HTMLElement>('button:not([disabled])')?.focus());
  });
</script>

<aside class:mobile-open={open} class="sidebar" inert={narrow && !open}>
  <a class="brand" href="/review"
    ><span class="brand-icon"><AudioLines size={20} aria-hidden="true" /></span><span>DubTitlerr</span></a
  >
  <nav aria-label="Primary navigation" aria-busy={busy} bind:this={navEl}>
    {#each ITEMS as item (item.key)}
      {@const Icon = item.icon}
      <button
        class:nav-active={view === item.key}
        aria-current={view === item.key ? 'page' : undefined}
        onclick={() => onnavigate(item.key)}
        disabled={!authenticated}
        ><Icon size={18} aria-hidden="true" />{item.label}{#if item.key === 'inbox'}<span class="nav-count"
            >{authenticated ? count : '—'}</span
          >{/if}</button
      >
      {#if item.key === 'settings' && view === 'settings'}
        <ul class="subnav" aria-label="Settings categories">
          {#each SETTINGS_CATEGORIES as c (c.id)}
            <li>
              <a
                href={settingsHash(c.id)}
                class:nav-active={settingsCategory === c.id}
                aria-current={settingsCategory === c.id ? 'page' : undefined}
                onclick={() => onpick?.()}>{c.label}</a
              >
            </li>
          {/each}
        </ul>
      {/if}
    {/each}
  </nav>
  <div class="sidebar-bottom">
    <a href="/" class="classic-link"><ExternalLink size={15} aria-hidden="true" />Classic review</a>
    <div class="version-line">Review workspace v0.1</div>
  </div>
</aside>

<style>
  .subnav {
    list-style: none;
    margin: 0 0 4px;
    padding: 0;
    display: grid;
    gap: 1px;
  }
  .subnav a {
    display: block;
    padding: 6px 12px 6px 40px;
    border-left: 3px solid transparent;
    color: var(--muted);
    text-decoration: none;
  }
  .subnav a:hover {
    background: var(--surface);
    color: var(--text);
  }
  .subnav a:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }
  .subnav a.nav-active {
    color: var(--text);
    background: var(--surface);
    border-left-color: var(--accent);
  }
</style>
