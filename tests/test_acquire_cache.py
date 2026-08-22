"""Per-token decision cache for glossary_acquire.

Measured on One Pace (462 episodes): `settled` was 107 terms against 8,199 harvested, so
~99% of the work repeated every sweep -- including 371 LLM calls in escalate, 71% of the
stage's runtime. It blew a 1800s timeout three sweeps running and never once completed.

The design's load-bearing claim is "absence is the cache miss" -- no fingerprint, no TTL.
These tests pin the two places that claim does NOT cover."""
import json
import os
import stat

import pytest

import acquire_cache as ac

NORM = lambda s: s.strip()          # stand-in for normalize_title in these unit tests


def test_absence_is_the_cache_miss(tmp_path):
    g = str(tmp_path / "Show.json")
    assert ac.load(g) == {}
    assert ac.skippable({}, {"luffy": 5}, lambda t: None, {"Luffy"}, NORM) == set()


def test_a_cached_verdict_short_circuits_the_token(tmp_path):
    cache = {"luffy": {"verdict": "apply", "canonical": "Luffy", "count": 40}}
    assert ac.skippable(cache, {"luffy": 41}, lambda t: None, {"Luffy"}, NORM) == {"luffy"}


def test_a_renamed_canonical_invalidates_only_that_entry():
    """The gap 'absence is the cache miss' does not cover. fetch_titles re-fetches on a
    30-day TTL, so a wiki rename would otherwise write a dead title into hard_fixes
    forever."""
    cache = {"luffy": {"verdict": "apply", "canonical": "Luffy", "count": 40},
             "zoro":  {"verdict": "apply", "canonical": "Zoro",  "count": 30}}
    titles = {"Luffy"}                              # "Zoro" was renamed away
    assert ac.skippable(cache, {"luffy": 40, "zoro": 30}, lambda t: None, titles, NORM) \
        == {"luffy"}


def test_structural_junk_never_recycles_at_any_count():
    for reason in ("english-word", "already-canonical", "sentence-initial-only"):
        e = {"verdict": "junk", "reason": reason, "count": 2}
        assert ac.is_fresh(e, 100000, None, set(), NORM) is True, reason
        assert ac.recycles(reason) is False


def test_every_non_structural_junk_reason_recycles():
    """Naming only `below-floor` would permanently junk four other corpus-derived
    verdicts -- the long-tail names the recycling rule exists to rescue."""
    for reason in ("below-floor", "unseen-needs-evidence", "share-too-close",
                   "transcript-new-term", "growth-over-cap"):
        assert ac.recycles(reason) is True, reason
        e = {"verdict": "junk", "reason": reason, "count": 2}
        assert ac.is_fresh(e, 7, None, set(), NORM) is False, reason


def test_junk_recycles_only_on_MATERIAL_growth():
    e = {"verdict": "junk", "reason": "below-floor", "count": 10}
    assert ac.is_fresh(e, 25, None, set(), NORM) is True      # 2.5x -- not yet
    assert ac.is_fresh(e, 31, None, set(), NORM) is False     # past 3x -- reconsider


def test_junk_recycles_when_its_floor_anchor_moved():
    """A below-floor verdict rests on whether a near-miss is in anchor_terms, and that set
    grows as applies accumulate."""
    e = {"verdict": "junk", "reason": "below-floor", "count": 5, "floor_anchor": None}
    assert ac.is_fresh(e, 5, None, set(), NORM) is True
    assert ac.is_fresh(e, 5, "Shirahoshi", set(), NORM) is False


def test_an_unrelated_junk_entry_stays_cached_when_another_anchor_moves():
    cache = {"a": {"verdict": "junk", "reason": "below-floor", "count": 5,
                   "floor_anchor": None},
             "b": {"verdict": "junk", "reason": "below-floor", "count": 5,
                   "floor_anchor": None}}
    anchors = {"a": "Shirahoshi", "b": None}
    got = ac.skippable(cache, {"a": 5, "b": 5}, lambda t: anchors[t], set(), NORM)
    assert got == {"b"}


def test_remember_stores_the_POST_escalate_verdict():
    """Called after source_gate, so the LLM outcome is what gets cached -- that is the 71%
    this module exists to stop repaying."""
    props = [{"variant": "gum-gum", "verdict": "apply", "canonical": "Gum-Gum",
              "reason": "wiki-exact", "settled_target": None, "variant_count": 41}]
    cache = ac.remember({}, props, {"gum-gum": 41})
    assert cache["gum-gum"]["verdict"] == "apply"
    assert cache["gum-gum"]["canonical"] == "Gum-Gum"
    assert cache["gum-gum"]["count"] == 41


def test_a_flag_verdict_is_stored_as_junk_with_its_reason():
    props = [{"variant": "spandom", "verdict": "flag", "reason": "below-floor",
              "canonical": "Spandam", "settled_target": None, "variant_count": 1}]
    cache = ac.remember({}, props, {"spandom": 1})
    assert cache["spandom"]["verdict"] == "junk"
    assert cache["spandom"]["reason"] == "below-floor"


def test_roundtrip_and_group_writable(tmp_path):
    g = str(tmp_path / "Show.json")
    assert ac.save(g, {"luffy": {"verdict": "apply", "canonical": "Luffy", "count": 3}})
    assert ac.load(g)["luffy"]["canonical"] == "Luffy"
    import common
    mode = stat.S_IMODE(os.stat(ac.path_for(g)).st_mode)
    assert mode == common.SIDECAR_MODE


def test_a_corrupt_cache_degrades_to_a_full_run(tmp_path):
    g = str(tmp_path / "Show.json")
    open(ac.path_for(g), "w").write("{not json")
    assert ac.load(g) == {}


def test_a_malformed_entry_costs_that_token_not_the_run():
    cache = {"good": {"verdict": "apply", "canonical": "Luffy", "count": 1},
             "bad": "not-a-dict"}
    assert ac.skippable(cache, {"good": 1, "bad": 1}, lambda t: None, {"Luffy"}, NORM) \
        == {"good"}


def test_save_never_raises_on_an_unwritable_path():
    assert ac.save("/nonexistent/dir/Show.json", {"a": {"verdict": "junk"}}) is False
