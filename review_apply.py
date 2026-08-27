#!/usr/bin/env python3
"""[S-5] Re-open an already-muxed episode so a human's verdicts reach the video.

[S-4] made a verdict change what the NEXT run of an episode ships. That leaves the whole
existing library carrying text a reviewer has since ruled on, muxed and stamped, with
nothing to re-trigger it. This module is that trigger.

WHAT AN ALREADY-MUXED EPISODE LOOKS LIKE ON DISK, and why it decides the whole design:
mux.py writes the stamp and then removes BOTH sidecars (mux.py:367-371); for a
signs-bearing mkv, dub_signs_merge.py:188 removes the srt earlier still. So a muxed
episode has conf.json and a stamp and NO subtitle sidecar at all -- the only remaining copy
of the shipped dialogue is inside the mkv. A write-back that tried to EDIT the existing srt
would therefore refuse every episode in the population it was written for.

So this does not edit; it re-opens. merge_pass.sh finds work by globbing for
`*.eng.dubtitles.srt`/`.ass` (merge_pass.sh:56), and with an srt present and no ass it
re-runs repair.py (merge_pass.sh:59) -- which consults the decision store and settles every
reviewed line. Writing a fresh srt from conf.json and dropping the stamp is exactly what
puts the episode back in that queue. Reproducing repair's output here would be both
redundant and a second place for the verdict logic to drift.

That is also why rebuilding from conf.json does not lose the LLM repairs: repair.py re-runs
immediately afterwards and re-derives them, applying the stored verdicts as it goes.

A stale `.ass` is REMOVED. mux.sub_source prefers it over the srt (mux.py:296-302) and
merge_pass only re-runs repair when no ass is present, so leaving one behind would re-mux
the old text and silently drop the verdict on the floor.

WHAT IT DOES NOT DO. No LLM call, no network, no re-judging: `repair.process()` would also
rebuild this srt, and would also be free to reach a different conclusion than the one the
human reviewed. An episode with no conf.json is refused by name -- tools/recover_dub_srt.py
is the tool for that case, and it reads the muxed track.

Env:
  DECISIONS_DIR  default /config/decisions   (see decisions.py)
  GLOSSARY_DIR   default /config/glossaries  (used only to resolve which show a path is in)
"""

import argparse
import json
import os
import tempfile

import decisions
import reflow
from common import MEDIA_GID, MEDIA_UID, SIDECAR_MODE, STAMP_SUFFIX, log, ts_srt

# The SAME fits_card repair.py applies, imported rather than reimplemented. Two writers of
# the shipped srt that disagreed about C1 would mean a `correct` refused on a re-run and
# applied by a sweep, and the drift would be invisible until an episode shipped an
# unreadable card. Importing costs a module load and buys the guarantee.
from repair import fits_card

CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"
ASS_SUFFIX = ".eng.dubtitles.ass"


def _write_srt(path: str, rows: list, texts: list) -> None:
    """Atomic temp + os.replace, mirroring generate._atomic_write.

    Re-wrapped through reflow.wrap_balance, the same call repair.py's rebuild uses, so an
    UNCHANGED cue comes out byte-identical: conf.json stores text flattened, wrap_balance is
    deterministic, and the srt was written by that same call in the first place."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for i, (c, t) in enumerate(zip(rows, texts), 1):
                f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{reflow.wrap_balance(t)}\n\n")
        os.chmod(tmp, SIDECAR_MODE)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chown(path, MEDIA_UID, MEDIA_GID)
    except OSError:
        pass  # non-root, or a filesystem without it


def apply_episode(stem: str, store: dict, apply: bool = False) -> dict:
    """Re-open this episode if any stored verdict names one of its lines. Dry-run unless
    ``apply``.

    "Names one of its lines" is matched on the ORIGINAL text only, which is all conf.json
    holds -- the proposal that was actually applied lives in the muxed track and is gone
    from disk. That is enough to decide ELIGIBILITY, and eligibility is all this decides:
    repair.py re-runs afterwards and applies the verdicts through the full pair key."""
    res = {"stem": stem, "changed": 0}
    try:
        rows = json.load(open(stem + CONF_SUFFIX, encoding="utf-8"))
    except (OSError, ValueError):
        res["error"] = "no conf.json"
        return res
    if not isinstance(rows, list):
        res["error"] = "conf.json is not a list of cards"
        return res

    texts, changed = [], 0
    for c in rows:
        orig = (c or {}).get("text", "")
        want = orig
        ruled = decisions.for_orig(store, orig) if orig else []
        if ruled:
            changed += 1
            corrected = next((e for e in ruled if e.get("verdict") == "correct"), None)
            human = (corrected or {}).get("text") or ""
            # C1: card timing is immutable, for a human too. repair.py refuses an
            # unrenderable `correct` and queues the refusal; here the ASR text simply
            # stands, and repair.py re-records the refusal on its next pass.
            if human and fits_card(human, float(c.get("end", 0)) - float(c.get("start", 0)), orig):
                want = human
        texts.append(want)

    res["cards"] = len(rows)
    res["changed"] = changed
    if not changed or not apply:
        return res

    _write_srt(stem + SRT_SUFFIX, rows, texts)
    # The stale .ass must go, or mux embeds it and ignores the srt just written -- and
    # merge_pass skips repair.py, so the verdict never reaches the video. Silent, because
    # every other part of the run still reports success.
    try:
        os.remove(stem + ASS_SUFFIX)
        res["ass_dropped"] = True
    except OSError:
        pass
    # Stamp LAST, and only once the sidecar is on disk. mux.py treats a valid stamp as its
    # only skip guard (mux.py:330), so this is what re-opens the episode; dropping it first
    # would leave a window with no stamp AND no sidecar, which merge_pass cannot even find.
    stamp = stem + STAMP_SUFFIX
    if os.path.exists(stamp):
        os.remove(stamp)
        res["stamp_dropped"] = True
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Apply stored human repair decisions to already-generated episodes.")
    ap.add_argument("target", help="an episode stem, or a directory to sweep")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    a = ap.parse_args(argv)

    stems = [a.target] if os.path.exists(a.target + CONF_SUFFIX) else _walk(a.target)
    # Resolved PER EPISODE, cached per show. Resolving once from the first episode found is
    # wrong the moment a sweep spans two shows -- and wrong in silence, because episodes
    # checked against another show's store report 0 changed, which reads exactly like
    # "nothing to fix". A sweep of a whole library is the expected use, not an edge case.
    stores: dict = {}
    changed_eps, refused, unresolved_shows = 0, 0, set()
    for stem in stems:
        show_key = os.path.dirname(stem)
        if show_key not in stores:
            stores[show_key] = decisions.decisions_for(stem)
        store, show = stores[show_key]
        if not show:
            # An empty store and an unresolvable show produce the same "0 changed" output.
            # Only one of them is good news, so they must not look alike.
            if show_key not in unresolved_shows:
                unresolved_shows.add(show_key)
                log(f"  WARNING: no decision store resolves for {show_key or stem} — check GLOSSARY_DIR/DECISIONS_DIR")
        res = apply_episode(stem, store, apply=a.apply)
        if res.get("error"):
            refused += 1
            log(f"  REFUSED {os.path.basename(stem)}: {res['error']}")
            continue
        if res["changed"]:
            changed_eps += 1
            log(f"  {'APPLIED' if a.apply else 'PLAN'} {os.path.basename(stem)}  {res['changed']} card(s)")
    log(
        json.dumps(
            {
                "episodes": len(stems),
                "changed": changed_eps,
                "refused": refused,
                "unresolved_shows": len(unresolved_shows),
                "written": a.apply,
            }
        )
    )
    return 0


def _walk(root: str) -> list:
    out = []
    for dp, _dns, fs in os.walk(root):
        out += [os.path.join(dp, f[: -len(CONF_SUFFIX)]) for f in fs if f.endswith(CONF_SUFFIX)]
    return sorted(out)


if __name__ == "__main__":
    raise SystemExit(main())
