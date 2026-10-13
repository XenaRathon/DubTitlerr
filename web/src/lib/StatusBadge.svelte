<script module lang="ts">
  /** The one status vocabulary shared by the dashboard, the runs page and the inbox (specs/servarr-restyle, Step 3). */
  export type Status = 'pending' | 'running' | 'done' | 'failed' | 'stale';

  /** Pipeline stages (review_status.STAGES) folded onto the shared vocabulary; the stage stays the visible label. */
  export const STAGE_STATUS: Record<string, Status> = {
    transcribed: 'running',
    repaired: 'running',
    'pending-review': 'pending',
    muxed: 'done',
    failed: 'failed',
    stale: 'stale',
  };
</script>

<script lang="ts">
  import { CircleCheck, CircleQuestionMark, CircleX, Clock, History, RefreshCw } from '@lucide/svelte';

  let {
    status,
    label,
  }: {
    /** A word from the shared vocabulary; anything else renders as a neutral, unknown status. */
    status: string | null | undefined;
    /** Visible text; defaults to the status word. */
    label?: string;
  } = $props();

  const TONES: Record<Status, string> = {
    pending: 'warn',
    running: 'info',
    done: 'ok',
    failed: 'bad',
    stale: 'muted',
  };
  const ICONS = { pending: Clock, running: RefreshCw, done: CircleCheck, failed: CircleX, stale: History };

  const known = $derived(
    status && Object.prototype.hasOwnProperty.call(TONES, status) ? (status as Status) : null,
  );
  const Icon = $derived(known ? ICONS[known] : CircleQuestionMark);
</script>

<!-- The icon is decoration: the word carries the meaning, so the badge never relies on colour or shape alone. -->
<span class="badge" data-tone={known ? TONES[known] : 'muted'} data-status={known ?? 'unknown'}
  ><Icon size={14} aria-hidden="true" />{label ?? status ?? 'unknown'}</span
>
