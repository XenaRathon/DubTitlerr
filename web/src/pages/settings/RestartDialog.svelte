<script lang="ts">
  let {
    labels,
    portChanged = false,
    onlater,
    onnow,
  }: {
    labels: string[];
    /** REVIEW_PORT is among the saved keys: the compose port mapping has to follow it. */
    portChanged?: boolean;
    onlater: () => void;
    onnow: () => void;
  } = $props();
  let dialog = $state<HTMLDialogElement>();
  $effect(() => {
    if (dialog && !dialog.open) dialog.showModal();
  });
</script>

<dialog bind:this={dialog} class="help-panel" aria-labelledby="restart-title" onclose={onlater}>
  <div class="panel-title"><h2 id="restart-title">Restart required</h2></div>
  <p>Saved. These settings take effect only after the builder restarts: {labels.join(', ')}.</p>
  {#if portChanged}
    <p>
      The compose port mapping must match the new web UI port before you restart, or the page becomes
      unreachable.
    </p>
  {/if}
  <p>
    Restart Now finishes the episode in flight, then stops the builder. It starts again only if the container
    has a restart policy of unless-stopped or always.
  </p>
  <div class="dialog-actions">
    <button class="secondary" type="button" onclick={onlater}>Restart Later</button>
    <button class="primary" type="button" onclick={onnow}>Restart Now</button>
  </div>
</dialog>

<style>
  .dialog-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 12px;
  }
</style>
