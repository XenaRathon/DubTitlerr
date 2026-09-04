"""[S-5] write-back: re-open an already-muxed episode so a human's verdicts reach the video.

The state this module actually targets, verified against mux.py:354-371: once an episode is
muxed the stamp EXISTS and both sidecars are GONE -- mux removes `.eng.dubtitles.srt` and
`.eng.dubtitles.ass` immediately after stamping, and dub_signs_merge.py:188 removes the srt
earlier still. conf.json survives. So a fixture holding a stamp AND an srt at the same time
describes a state this pipeline never produces, and a module that reads the srt to learn
what shipped can never run on the library it was written for.

What re-opens an episode is therefore writing a sidecar, not editing one: merge_pass.sh:56
finds work by globbing for `*.eng.dubtitles.srt`/`.ass`, and with an srt present and no ass
it re-runs repair.py (merge_pass.sh:59), which consults the decision store ([S-4]) and
settles every reviewed line. This module's job is to put the episode back in that queue,
not to reproduce repair's output."""

import json
import os

import common
import decisions
import review_apply

CONF = ".dubtitles.conf.json"
SRT = ".eng.dubtitles.srt"
ASS = ".eng.dubtitles.ass"
STAMP = ".dubtitles.done"


def _muxed(tmp_path, name, rows, ass=False):
    """An episode as mux.py leaves it: conf.json and a stamp, NO sidecar."""
    stem = str(tmp_path / name)
    with open(stem + CONF, "w") as f:
        json.dump(rows, f)
    with open(stem + STAMP, "w") as f:
        json.dump({"muxed": True, "version": 7}, f)
    if ass:  # a signs-bearing episode caught between merge and mux
        with open(stem + ASS, "w") as f:
            f.write("[Events]\nDialogue: 0,0:00:00.00,0:00:02.00,Dubtitles,,0,0,0,,I saw Spandam\n")
    return stem


def _cues(path):
    """(timing, text) per cue, so a wrap-placement change cannot hide behind a flatten."""
    out = []
    for block in open(path).read().strip().split("\n\n"):
        lines = block.split("\n")
        out.append((lines[1], "\n".join(lines[2:])))
    return out


def _no_llm(*a, **k):
    raise AssertionError("review_apply must never call the LLM backend")


def test_an_already_muxed_episode_gets_a_sidecar_and_loses_its_stamp(tmp_path, monkeypatch):
    """The core case, and the one the previous fixture could not express.

    No srt exists. The module must WRITE one from conf.json and drop the stamp, because
    those two facts together are what merge_pass.sh and mux.py use to find work. Asserted
    on the backend never being called: repair.py rebuilds the same srt from the same
    conf.json, so a criterion that only checked the file would be satisfied by re-running
    repair -- which is what this module must not do."""
    rows = [
        {"start": 0.0, "end": 2.0, "text": "I saw spondum"},
        {"start": 2.0, "end": 4.0, "text": "the ship sailed"},
    ]
    stem = _muxed(tmp_path, "ep1", rows)
    monkeypatch.setattr(common, "llm_chat", _no_llm)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    res = review_apply.apply_episode(stem, store, apply=True)

    assert os.path.exists(stem + SRT), "a sidecar is what re-opens the episode for merge_pass"
    assert [t for _, t in _cues(stem + SRT)] == ["I saw spondum", "the ship sailed"]
    assert res["changed"] == 1, "one conf row matches a stored decision"
    assert not os.path.exists(stem + STAMP), "the stamp must drop so mux re-runs"


def test_a_stale_ass_is_removed_so_the_rebuilt_srt_is_not_ignored(tmp_path):
    """mux.sub_source (mux.py:296-302) prefers the .ass and falls back to the .srt, and
    merge_pass.sh:58 only re-runs repair when no .ass is present. Leaving a stale .ass
    behind means the episode re-muxes the OLD text and the verdict never reaches the video
    -- silently, because everything else about the run looks successful."""
    rows = [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_ass", rows, ass=True)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    review_apply.apply_episode(stem, store, apply=True)

    assert not os.path.exists(stem + ASS), "a stale .ass would win over the srt we just wrote"
    assert os.path.exists(stem + SRT)


def test_an_episode_no_decision_matches_is_left_completely_alone(tmp_path):
    """Throwing away a stamp costs a re-mux of a multi-GB file. An episode no stored
    decision mentions must keep its stamp and gain no sidecar -- otherwise one verdict
    would re-mux an entire show."""
    rows = [{"start": 0.0, "end": 2.0, "text": "he went thataway"}]
    stem = _muxed(tmp_path, "ep_untouched", rows)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    res = review_apply.apply_episode(stem, store, apply=True)

    assert res["changed"] == 0
    assert os.path.exists(stem + STAMP), "an unaffected episode keeps its stamp"
    assert not os.path.exists(stem + SRT), "and gains no sidecar"


def test_dry_run_writes_nothing_and_reports_the_plan(tmp_path):
    """Repo convention (mux.py, glossary_acquire.py, tools/reapply_glossary.py)."""
    rows = [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_dry", rows)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    res = review_apply.apply_episode(stem, store)

    assert res["changed"] == 1, "the plan still reports what WOULD change"
    assert not os.path.exists(stem + SRT) and os.path.exists(stem + STAMP), "dry run writes nothing"


def test_a_missing_conf_json_is_refused_by_name_and_leaves_the_stamp(tmp_path):
    """conf.json is the only surviving source for a muxed episode, so without it there is
    nothing to rebuild from. tools/recover_dub_srt.py is the tool for that case, and it
    reads the muxed track. A half-applied episode is the failure to avoid."""
    stem = str(tmp_path / "ep_noconf")
    with open(stem + STAMP, "w") as f:
        json.dump({"muxed": True}, f)

    res = review_apply.apply_episode(stem, {"decisions": []}, apply=True)

    assert res["error"] == "no conf.json"
    assert res["stem"] == stem, "refused BY NAME -- a silent skip is what this guards against"
    assert os.path.exists(stem + STAMP), "an episode we cannot rebuild keeps its stamp"


def test_a_correct_verdict_supplies_the_humans_text_and_still_obeys_fits_card(tmp_path):
    """C1 in the second actor that writes this file. repair.py refuses an unrenderable
    `correct`; if the write-back did not, the two writers of the shipped srt would disagree
    about the one rule that is not negotiable. Sprint 004's lesson: enumerate every actor
    that writes the same value."""
    rows = [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}]
    fits = _muxed(tmp_path, "ep_fit", rows)
    unfit = _muxed(tmp_path, "ep_unfit", rows)
    ok = decisions.record({}, "I saw spondum", "I saw Spandam", "correct", text="I saw Spandam over there")
    too_long = decisions.record(
        {}, "I saw spondum", "I saw Spandam", "correct", text="I saw Spandam standing over there beside the harbour gate"
    )

    review_apply.apply_episode(fits, ok, apply=True)
    review_apply.apply_episode(unfit, too_long, apply=True)

    assert "I saw Spandam over there" in open(fits + SRT).read(), "a renderable correction is written"
    assert "harbour" not in open(unfit + SRT).read(), "the write-back cannot widen a card either"


def test_a_correct_too_wide_for_one_line_but_splittable_ships_as_two_cues(tmp_path):
    """The other writer of the same rule. repair.py's process() and review_apply.py's
    apply_episode() must not disagree about what a legal split is, or a correction split
    on one re-run and refused on the other. Same verified fixture as repair.py's own test:
    at 10.0s the 84-char correction is over_line_len only (no over_cps), and the sentence-
    boundary split gives two individually legal single-line halves."""
    half1 = "The captain ordered everyone to abandon ship at once."
    half2 = "Nobody thought twice about it."
    rows = [{"start": 100.0, "end": 110.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_split", rows)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "correct", text=f"{half1} {half2}")

    review_apply.apply_episode(stem, store, apply=True)

    cues = _cues(stem + SRT)
    assert len(cues) == 2, "two cues, not one -- a single cue could never legally hold this text"
    joined = "\n".join(t for _, t in cues)
    assert "abandon ship at once" in joined and "Nobody thought twice" in joined


def test_a_show_sweep_invalidates_only_the_episodes_that_change(tmp_path):
    """Three episodes, one verdict."""
    hit = _muxed(tmp_path, "ep_a", [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}])
    miss1 = _muxed(tmp_path, "ep_b", [{"start": 0.0, "end": 2.0, "text": "the ship sailed"}])
    miss2 = _muxed(tmp_path, "ep_c", [{"start": 0.0, "end": 2.0, "text": "he went thataway"}])
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    for stem in (hit, miss1, miss2):
        review_apply.apply_episode(stem, store, apply=True)

    assert not os.path.exists(hit + STAMP), "the episode that changed is re-opened"
    assert os.path.exists(miss1 + STAMP) and os.path.exists(miss2 + STAMP), "untouched episodes keep their stamps"


def test_the_rebuilt_srt_wraps_long_cards_the_way_the_pipeline_does(tmp_path):
    """Every fixture above is under MAX_LINE, so none of them exercise wrap_balance's
    multi-line branch -- the previous suite asserted byte-identity nowhere near it. A card
    long enough to wrap must come out wrapped, and compared WITH its line breaks."""
    long_text = "This is a much longer line of dialogue that has to wrap across two lines"
    rows = [{"start": 0.0, "end": 8.0, "text": long_text}]
    stem = _muxed(tmp_path, "ep_wrap", rows)
    store = decisions.record({}, long_text, "whatever", "reject")

    review_apply.apply_episode(stem, store, apply=True)

    import reflow

    assert _cues(stem + SRT)[0][1] == reflow.wrap_balance(long_text)
    assert "\n" in _cues(stem + SRT)[0][1], "the fixture must actually reach the wrapping branch"


def test_a_sweep_resolves_the_store_per_show_not_once(tmp_path, monkeypatch, capsys):
    """A sweep that spans two shows must not check both against one show's verdicts.

    Resolving the store once from the first episode found is silent when it is wrong: the
    other show's episodes report `changed: 0` with no error, which is indistinguishable
    from "no verdicts recorded for them". Nothing crashes and nothing is written -- the
    operator is simply told the wrong thing."""
    a = tmp_path / "Show A" / "S1"
    b = tmp_path / "Show B" / "S1"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    ep_a = _muxed(a, "a1", [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}])
    ep_b = _muxed(b, "b1", [{"start": 0.0, "end": 2.0, "text": "he went thataway"}])
    store_a = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")
    store_b = decisions.record({}, "he went thataway", "he went that way", "reject")

    def fake_decisions_for(path, *a_, **k):
        return (store_a, "Show A") if "Show A" in path else (store_b, "Show B")

    monkeypatch.setattr(decisions, "decisions_for", fake_decisions_for)
    review_apply.main([str(tmp_path), "--apply"])

    assert not os.path.exists(ep_a + STAMP), "Show A's verdict must apply to Show A"
    assert not os.path.exists(ep_b + STAMP), "Show B's verdict must apply to Show B"


def test_a_show_that_cannot_be_resolved_is_reported_not_silently_empty(tmp_path, monkeypatch, capsys):
    """An unresolvable show yields an empty store, and every episode then reports 0 changed
    -- the same output as "nothing to fix". A misconfigured GLOSSARY_DIR/DECISIONS_DIR would
    look like a clean run. It has to say so."""
    ep = _muxed(tmp_path, "orphan", [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}])
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: ({}, ""))

    review_apply.main([str(tmp_path)])

    assert "no decision store" in capsys.readouterr().out.lower(), "silence here reads as success"
    assert os.path.exists(ep + STAMP)


# --- [F-3] the write-back against a signs merge that fails -------------------
# Both pre-merge reviews reached this path and disagreed about it, which is why it gets a
# test rather than an argument. `dub_signs_merge.build()` returns "no-signs", 0, 0 at
# dub_signs_merge.py:127 -- BEFORE writing any .ass -- and process_one can also return
# "build-error" (:181) or "no-video" (:176), or "empty" when build succeeded with dub == 0.


def _merged_episode(tmp_path, name="ep_signs"):
    """A muxed, signs-bearing episode: conf.json + stamp, no sidecar, plus the stale .ass
    that mux would have removed had it not been muxed from one."""
    rows = [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, name, rows, ass=True)
    return stem, rows


def test_a_write_back_leaves_a_muxable_sidecar_when_signs_cannot_be_merged(tmp_path):
    """The outcome asserted, not assumed.

    review_apply removes the stale .ass and writes an .srt. If the next pass's signs merge
    returns no-signs, no .ass is produced and the .srt is NOT removed
    (dub_signs_merge.py:127 returns before both), so mux.sub_source falls back to the srt
    and the episode still muxes -- carrying the human's verdict, without signs that pass.

    That is recoverable rather than lost, which is what the rebuttal argued. It is asserted
    here so the next reader does not have to re-derive it from two contradicting reviews."""
    stem, _ = _merged_episode(tmp_path)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    review_apply.apply_episode(stem, store, apply=True)

    assert os.path.exists(stem + SRT), "an srt is what mux falls back to when there is no ass"
    assert not os.path.exists(stem + ASS), "and the stale ass is gone, or it would win and ship the old text"
    assert not os.path.exists(stem + STAMP), "the episode is re-opened either way"


def test_the_write_back_is_idempotent_across_a_failed_signs_pass(tmp_path):
    """A failing signs merge leaves the srt in place, so the next merge sweep finds the same
    sidecar and runs the whole thing again. Re-running the write-back on that state must not
    compound: same sidecar, same stamp state, no second stale ass."""
    stem, _ = _merged_episode(tmp_path)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    first = review_apply.apply_episode(stem, store, apply=True)
    srt_after_first = open(stem + SRT).read()
    second = review_apply.apply_episode(stem, store, apply=True)

    assert first["changed"] == second["changed"] == 1
    assert open(stem + SRT).read() == srt_after_first, "a second pass changes nothing"
    assert not os.path.exists(stem + ASS)


def test_an_episode_that_never_had_signs_is_handled_the_same_way(tmp_path):
    """The counterpart, so the test above is not just describing the ass-removal branch. A
    dialogue-only episode has no ass to remove and must still be re-opened."""
    rows = [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_nosigns", rows, ass=False)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    res = review_apply.apply_episode(stem, store, apply=True)

    assert res["changed"] == 1 and res.get("ass_dropped") is None
    assert os.path.exists(stem + SRT) and not os.path.exists(stem + STAMP)


def test_removing_a_stale_ass_is_recorded_so_a_lost_signs_pass_is_noticeable(tmp_path):
    """ "Recoverable" requires someone noticing. An episode that HAD signs and comes back
    without them is only distinguishable from one that never had them if the write-back says
    it dropped an ass -- nothing downstream can tell afterwards, because the ass is gone."""
    signs, _ = _merged_episode(tmp_path, "ep_had_signs")
    plain = _muxed(tmp_path, "ep_never_had", [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}], ass=False)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    had = review_apply.apply_episode(signs, store, apply=True)
    never = review_apply.apply_episode(plain, store, apply=True)

    assert had.get("ass_dropped") is True
    assert never.get("ass_dropped") is None, "the two cases must be distinguishable in the result"


def test_an_untimed_word_in_the_card_falls_back_instead_of_raising(tmp_path):
    """R-B2. A persisted words.json is ALLOWED to hold a word with no timing of its own --
    punctuation.restore() inserts them, and repair's window helper is written to exclude
    them so card_split degrades to the proportional fallback. review_apply filtered the
    window itself with `w.get("start", 0) >= start`, which compares None against a float
    and raises TypeError before that fallback can ever be reached: the Apply endpoint
    returned no srt and left the stamp in place, so the reviewed correction never shipped.
    Both writers now select the window through card_split.card_words."""
    half1 = "The captain ordered everyone to abandon ship at once."
    half2 = "Nobody thought twice about it."
    rows = [{"start": 100.0, "end": 110.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_untimed", rows)
    with open(stem + ".dubtitles.words.json", "w") as f:
        json.dump(
            {
                "transcribe_version": common.TRANSCRIBE_VERSION,
                "words": [
                    {"word": "I", "start": 100.0, "end": 100.5},
                    {"word": "saw", "start": 101.0, "end": None},  # restore() inserted, no timing
                    {"word": "spondum", "start": 102.0, "end": 103.0},
                ],
            },
            f,
        )
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "correct", text=f"{half1} {half2}")

    res = review_apply.apply_episode(stem, store, apply=True)

    assert not res.get("error"), res
    cues = _cues(stem + SRT)
    assert len(cues) == 2, "the untimed word must degrade to proportional, not abort the split"
    assert not os.path.exists(stem + STAMP)


def test_the_newest_dated_correction_wins_not_the_first_one_written(tmp_path):
    """R-5. `record` replaces per (orig, proposed) pair, so ONE original legitimately holds
    two corrections made against different proposals -- and decisions.corrected_text picks
    the later by `at` (decisions.py:184). review_apply used `next(...)` over file order and
    could write the superseded wording into the reopening srt; if the merge pass then
    stopped before repair.py re-derived it, the visible artifact was the human decision
    they had already replaced."""
    rows = [{"start": 0.0, "end": 4.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_two_corrections", rows)
    store = decisions.record({}, "I saw spondum", "I saw Spandine", "correct", text="old wording")
    store = decisions.record(store, "I saw spondum", "I saw Spandam", "correct", text="new wording")
    # File order is the trap: the superseded entry is first, and it is the older `at`.
    entries = store["decisions"]
    assert entries[0]["text"] == "old wording" and entries[0]["at"] <= entries[1]["at"]

    review_apply.apply_episode(stem, store, apply=True)

    assert [t for _, t in _cues(stem + SRT)] == ["new wording"]


def test_a_rejection_reopens_because_it_reverts_a_repair_that_already_shipped(tmp_path):
    """R-4, closed as won't-fix 2026-09-02, and pinned here so it is not "optimised" again.

    It looks like a rejection cannot change anything -- it leaves the ASR text standing, so
    reopening for one looks like a multi-gigabyte remux for byte-identical output. That is
    wrong, and the reason is that `repair.py` NEVER REWRITES conf.json (it writes only its
    summary sidecar). So conf.json holds raw ASR while the SHIPPED track holds repair's
    output, which may be an auto-admitted repair no human ever approved.

    Rejecting that repair means "the ASR text stands", and the only way to make the video
    say so is to reopen, rebuild the srt from conf.json, and re-mux. The remux is the whole
    point: it REVERTS. Skipping it would leave the rejected repair on screen forever, with
    the store claiming the reviewer had settled the line."""
    rows = [{"start": 0.0, "end": 2.0, "text": "I saw spondum"}]
    stem = _muxed(tmp_path, "ep_reject_reverts", rows)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")

    res = review_apply.apply_episode(stem, store, apply=True)

    assert res["changed"] == 1, "a rejection must still reopen -- it reverts what shipped"
    assert not os.path.exists(stem + STAMP)
    assert "I saw spondum" in open(stem + SRT).read(), "and the rebuilt srt carries the ASR text"
