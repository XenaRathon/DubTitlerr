<script lang="ts">
  let { onstay, ondiscard }: { onstay: () => void; ondiscard: () => void } = $props();
  let dialog = $state<HTMLDialogElement>();
  $effect(() => {
    if (dialog && !dialog.open) dialog.showModal();
  });
</script>

<dialog bind:this={dialog} class="help-panel" aria-labelledby="unsaved-title" onclose={onstay}>
  <div class="panel-title"><h2 id="unsaved-title">Unsaved changes</h2></div>
  <p>This page has edits that are not saved yet. Leaving now drops them.</p>
  <div class="dialog-actions">
    <button class="secondary" type="button" onclick={onstay}>Stay and review</button>
    <button class="primary" type="button" onclick={ondiscard}>Discard</button>
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
