<script lang="ts">
  let { step, detail, onclose }: { step: 'waiting' | 'timeout'; detail: string; onclose: () => void } =
    $props();
  let dialog = $state<HTMLDialogElement>();
  $effect(() => {
    if (dialog && !dialog.open) dialog.showModal();
  });
</script>

<!-- Not dismissable while waiting: Escape is swallowed, because the page cannot be used until the builder is back. -->
<dialog
  bind:this={dialog}
  class="help-panel"
  aria-labelledby="restarting-title"
  oncancel={(e) => e.preventDefault()}
>
  <div class="panel-title"><h2 id="restarting-title">Restarting</h2></div>
  {#if step === 'waiting'}
    <p role="status">Restarting, finishing the current episode…</p>
    <p class="detail">{detail}</p>
  {:else}
    <p role="alert">
      The builder did not come back within 10 minutes. Without a restart policy of unless-stopped or always
      the container stays down: start it by hand.
    </p>
    <button class="primary" type="button" onclick={onclose}>Close</button>
  {/if}
</dialog>

<style>
  .detail {
    color: var(--muted);
  }
</style>
