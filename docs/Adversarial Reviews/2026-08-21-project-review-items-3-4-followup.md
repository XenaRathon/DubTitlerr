# Project review follow-up — items 3 and 4

**Scope:** item 3 (`PIPELINE_VERSION` / idempotency), item 4 (the next “configuration looks applied” failure), and one confidence audit of the earlier VAD review.

## 3. Is global `PIPELINE_VERSION` the right idempotency key?

**No. It is a useful global invalidation switch, but it is not the right idempotency key.** It is too coarse for changes that affect only one stage, and too weak to detect several changes that do affect the output.

### The current stamp answers the wrong question

`common.write_stamp()` records:

```text
video size
video mtime
muxed = true
PIPELINE_VERSION
```

`stamp_valid()` then asks whether the current video has a matching stamp whose version is **at least** the running version. That answers:

> “Has some version at least this old produced a muxed file with these two filesystem metadata values?”

Idempotency needs to answer:

> “Does this exact source, with this exact audio selection and this exact stage configuration, already have the artifact I am about to trust?”

Those are not equivalent.

### Failure mode A — a text-only change is either over-invalidated or never applied

The pipeline has at least two materially different invalidation classes:

1. **transcription/timing changes:** Whisper model, audio filter, beam settings, punctuation-before-splitting, reflow rules, or the proposed VAD trim;
2. **text/render changes:** glossary contents, repair model/backend/prompt, signs merge rules, or ASS/SRT rendering.

A global version bump treats both as “re-transcribe every episode.” That is wasteful and increases the failure surface: a glossary-only correction should not require a new GPU transcription, and a mux/render-only fix should not make every source episode pass through Whisper again.

Conversely, changing a text-stage input without bumping the global version does nothing to already-muxed episodes. After a successful mux, `generate.py` has removed the SRT/conf sidecars. The current `.done` stamp makes `generate.process()` return `already-muxed`, and there is no stage fingerprint telling the merge loop that the existing track is stale. The new glossary or repair setting therefore remains unapplied while the episode looks current.

The existing `recreate_srt.py` can recover some intermediate material, but recovery is not a provenance model. It is a rescue path after the normal stage artifacts have already been deleted.

### Failure mode B — the stamp accepts output from a newer pipeline

This is a concrete correctness bug, not merely a design preference:

```python
if version is None or version < PIPELINE_VERSION:
    return False
return _stamp_matches_file(stamp, video)
```

A runtime at version 3 accepts a stamp written by version 4. `stale_version_stamp()` also treats version 4 as not stale when running version 3. That may be intentional for a strictly backward-compatible rollback, but no compatibility contract exists, and the stamp does not record whether version 4's output is readable by version 3.

If version 4 changes the subtitle schema, track policy, or media rewrite behavior, rolling back the container silently trusts an artifact the older code was never tested against. For a version identifier, exact equality is the safer default; a deliberate rollback should be an explicit migration decision, not an accidental consequence of `>=`.

**Check:** add a test with a future-version stamp and run both `stamp_valid()` and `stale_version_stamp()`. The current implementation will accept it as current.

### Failure mode C — size + mtime is an identity approximation

A replaced media file can retain both size and mtime, whether through a same-size replacement, a copied timestamp, or filesystem metadata behavior. The stamp then describes the old media but validates the new file.

This is less likely than the stage-fingerprint problem, but the cost is high: the pipeline skips a file while presenting old captions as current. The current tests cover a changed size, not a same-size replacement with preserved mtime.

**Evidence needed:** a test that replaces the bytes while restoring the original size and mtime, then checks whether the stamp is accepted. If the operational storage guarantees immutable media once stamped, record that guarantee; otherwise the stamp needs a content identity stronger than two stat fields.

### What should replace it

Keep `PIPELINE_VERSION` as a manual emergency invalidation knob, but stop making it the only provenance field. Use stage-specific fingerprints:

```text
source_identity:
  media content identity or an explicitly documented immutable-file contract
  selected audio stream identity

transcript_fingerprint:
  generator/reflow schema version
  Whisper model identity and model checksum/build identity
  compute/beam/threshold settings that affect output
  audio-filter settings
  punctuation/VAD settings
  glossary/prompt inputs if they affect transcription

render_fingerprint:
  glossary content hash
  repair backend + loaded-model identity + prompt/schema version
  signs/mux/render rules
```

Then use separate artifacts and skip decisions:

- same source + same transcript fingerprint → reuse transcription/confidence data;
- same transcript + same render fingerprint → skip assembly/mux;
- changed transcript fingerprint → regenerate downstream artifacts, and only re-transcribe when the transcription inputs changed.

The final `.done` stamp can still summarize the render artifact, but it should contain exact fingerprints, not only a global integer.

### Falsifiable predictions for item 3

1. A glossary-only change with `PIPELINE_VERSION` unchanged will leave an already-muxed episode untouched. Verify by changing the glossary and tracing `generate.process()` / `mux.process()`; both current guards are stamp/sidecar based.
2. A future-version stamp will be accepted by the current `stamp_valid()`. This is directly testable without media tooling.
3. A same-size, same-mtime byte replacement will be accepted unless another layer outside these functions detects it.
4. No current stamp field identifies the selected audio stream, model checksum, audio filter, glossary hash, repair backend, or mux policy. Grep `write_stamp()` and inspect its JSON payload; these inputs are absent.

## 4. Where is the next §5.5 silent-degradation bug?

### P0 — the active worker has a health detector but no health actuator

The active production compose is `docker/compose/dubtitles-3200g.yaml`. It contains:

```yaml
healthcheck:
  test: ["CMD-SHELL", "test -d '/media/Anime Library' && test -d /config"]
labels:
  autoheal: "true"
```

But the same file explicitly says that **no autoheal container exists on this node**. Docker's `restart: unless-stopped` restarts a process that exits; it does not restart a still-running container merely because its health status becomes `unhealthy`.

This reproduces the exact shape of the two earlier bugs:

```text
configuration says “autoheal: true”
healthcheck says “unhealthy”
operator reasonably infers “it will recover”
actual system: unhealthy container continues running
```

The failure is especially plausible here because the worker reaches the library over CIFS. A stale/dead mount can leave the Python/shell supervisor alive while generation and merge make no useful progress. The healthcheck can report the problem, but nothing in the active compose takes the corrective action.

**Repository evidence:**

```bash
rg -n 'autoheal|healthcheck' docker/compose/dubtitles-3200g.yaml docker/compose
```

The active file has the label and healthcheck but no `autoheal` service. The only autoheal service found in the compose tree belongs to the separate torrent stack.

**Runtime evidence that would settle the deployment state:**

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Label "autoheal"}}'
docker inspect dubtitle-builder --format '{{json .State.Health}}'
docker ps --filter label=autoheal
```

Do not infer that a container in `unhealthy` state is being restarted. Compare its container ID and restart count before and after a controlled healthcheck failure.

### P1 — the healthcheck proves directory existence, not that the worker can work

Even if an autoheal service is added, the current check can pass for the wrong mounted content:

- `/config` can exist but lack `anime_order.txt`;
- `/media/Anime Library` can exist but be empty or be the wrong share;
- the order file can exist but contain only missing show names.

`gen_loop.sh` treats a missing order file as “idle 300s,” and a missing show directory as `skip-missing`; the container remains alive. `merge_pass.sh` can `cd` into an empty but valid root, find no sidecars, print a normal completion line, and exit successfully. All of these states can look healthy to Docker while producing zero captions.

The fix is not “make `test -d` more complicated” alone. Add an application heartbeat and a readiness assertion with a known sentinel:

```text
startup/readiness: config manifest exists and is readable; configured media root is the expected mount
liveness: supervisor loops are alive
progress: last successful sweep, files considered, files changed, and last error timestamp
```

A healthcheck should fail on a stale progress heartbeat, not merely on a live shell and two directory entries. The watchdog then has something meaningful to act on.

### P1 — merge-stage failures are not propagated to the supervisor

`merge_pass.sh` invokes `repair.py`, `dub_signs_merge.py`, and `mux.py` without checking their exit statuses. It has no `set -e`, and the final `MERGE_PASS_DONE` line is printed regardless of per-episode failures.

That creates a second “looks applied” seam:

1. the repair endpoint is unavailable or `repair.py` fails;
2. the shell continues to signs merge and/or mux;
3. the episode may be muxed with the unrepaired SRT, or a failed mux may simply be skipped;
4. the pass reports completion and the supervisor sleeps normally.

This may be an intentional best-effort policy, but it is not an observable policy: the pass does not emit a failed-episode count or nonzero status for the supervisor to act on. A text repair outage can therefore be converted into a current `.done` artifact with no durable statement that the repair stage did not run.

**Evidence needed:** run a fixture with one forced `repair.py` failure and inspect whether the episode is muxed/stamped, whether the pass exits nonzero, and whether a durable QC/repair summary records “repair unavailable” distinctly from “no repair needed.”

### Item 4 conclusion

The strongest next finding is the **healthcheck/autoheal mismatch**, because the repository already documents the missing actuator while the deployment label makes the system look self-healing. The empty/wrong-mount case is the next likely false-green state after that. The repair-status propagation issue is the most likely content-quality false green inside an otherwise healthy container.

## Least-confident finding from the earlier VAD review

The single finding I am least confident in is:

> **A post-cascade VAD trim can move a displaced successor backward and undo the cascade's gap repair.**

I still think the mechanism is possible, but it depends on implementation details the design does not pin down:

- whether the hang gate uses settled display duration;
- whether trim is allowed to move `start` earlier than the settled display start;
- whether selected VAD intervals are clipped to source bounds;
- whether the implementation adds a predecessor clamp;
- whether any cascade-displaced successor remains hang-eligible after its duration was shortened.

The direct “cascade repaired a runt, then the same runt passes the hang gate” version is already weakened by the gate algebra: a repaired runt usually ends near `needed`, while eligibility requires more than `3.4 × needed` or 3 seconds. The successor version is the remaining claim, but I do not have a measured trace proving it occurs.

### Evidence that would settle it

One synthetic trace through the actual implementation, plus one real-data count:

1. Construct three groups that force `_cascade` to move the successor start later.
2. Make the successor retain a settled duration above the hang gate.
3. Give it a source window whose selected VAD speech starts before the cascade-shifted display start.
4. Run the actual trim and assert the final card against the predecessor and successor:

```text
final start >= previous final end + MIN_GAP
final end   <= next final start - MIN_GAP
final duration >= MIN_DUR
```

5. Run the same trace with the proposed implementation's real interval-selection and clipping code, not a mock trim helper.
6. On the 30 gated cards, record for each card whether it was cascade-displaced, its pre/post-cascade duration, its VAD-derived start, and whether the candidate would move earlier than the settled start.

If the synthetic case cannot be constructed under the actual gate and the real-data count is zero, I would retract this as a practical finding. If one case violates the invariant or any real card has that shape, the ordering objection stands.
