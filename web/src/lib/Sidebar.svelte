<script lang="ts">
  import { tick } from 'svelte';
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
    onnavigate,
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
    onnavigate: (next: View) => void;
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
    {/each}
  </nav>
  <div class="sidebar-bottom">
    <a href="/" class="classic-link"><ExternalLink size={15} aria-hidden="true" />Classic review</a>
    <div class="version-line">Review workspace v0.1</div>
  </div>
</aside>
