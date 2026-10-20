"""Per-pair adjudication cache for glossary_acquire's `escalate()`.

Measured on One Pace (462 episodes): `settled` was 107 terms against 8,199 harvested, so
~99% of the work repeated every sweep -- including 371 LLM calls in escalate, 71% of the
stage's runtime. It blew a 1800s timeout three sweeps running and never once completed.

An earlier version of this module cached the pipeline's FINAL verdict per token and folded
a hit into `settled`, which skipped the token everywhere downstream -- including out of the
review queue a dry run was supposed to report. Two byte-identical dry runs over One Pace
measured `proposed 641` then `proposed 0`. These tests pin the replacement: only
`escalate()`'s LLM adjudication is cached, keyed on the (variant, canonical) pair, so every
token still reaches propose()/source_gate() in full on every run."""

import os
import stat

import acquire_cache as ac


def test_absence_is_the_cache_miss(tmp_path):
    g = str(tmp_path / "Show.json")
    assert ac.load(g) == {}
    assert ac.escalation_for({}, "dothamingo", "Doflamingo") is None


def test_a_remembered_adjudication_is_served_back():
    cache = ac.remember_escalation({}, "dothamingo", "Doflamingo", {"same_entity": True, "confidence": "high"})
    assert ac.escalation_for(cache, "dothamingo", "Doflamingo") == {"same_entity": True, "confidence": "high"}


def test_the_pair_is_the_key_not_either_side_alone():
    """The same variant escalated against a DIFFERENT canonical is a different question and
    must not reuse the first answer."""
    cache = ac.remember_escalation({}, "kaido", "Kaido", {"same_entity": True, "confidence": "high"})
    assert ac.escalation_for(cache, "kaido", "Kaidou") is None


def test_a_low_confidence_or_negative_adjudication_is_cached_too():
    """A cache is a memo of the LLM's answer, not just of confirmations -- re-asking a
    question the model was unsure about wastes the same call the cache exists to avoid."""
    cache = ac.remember_escalation({}, "a", "B", {"same_entity": False, "confidence": "low"})
    assert ac.escalation_for(cache, "a", "B") == {"same_entity": False, "confidence": "low"}


def test_re_remembering_a_pair_replaces_its_entry():
    cache = ac.remember_escalation({}, "a", "B", {"same_entity": False, "confidence": "low"})
    cache = ac.remember_escalation(cache, "a", "B", {"same_entity": True, "confidence": "high"})
    assert ac.escalation_for(cache, "a", "B") == {"same_entity": True, "confidence": "high"}


def test_a_malformed_or_old_shape_entry_is_a_miss_not_an_error():
    """The old per-token cache stored `{token: {verdict, count, ...}}` -- a flat dict with
    no canonical-keyed nesting. Loading one of those files must degrade to a full run for
    every pair, never raise."""
    old_shape = {"luffy": {"verdict": "apply", "canonical": "Luffy", "count": 40}}
    assert ac.escalation_for(old_shape, "luffy", "Luffy") is None
    assert ac.escalation_for({"a": "not-a-dict"}, "a", "B") is None
    assert ac.escalation_for({"a": {"B": "not-a-dict"}}, "a", "B") is None
    assert ac.escalation_for({"a": {"B": {"confidence": "high"}}}, "a", "B") is None  # missing same_entity


def test_roundtrip_and_group_writable(tmp_path):
    g = str(tmp_path / "Show.json")
    cache = ac.remember_escalation({}, "a", "B", {"same_entity": True, "confidence": "high"})
    assert ac.save(g, cache)
    assert ac.load(g) == cache
    import common

    mode = stat.S_IMODE(os.stat(ac.path_for(g)).st_mode)
    assert mode == common.SIDECAR_MODE


def test_a_corrupt_cache_degrades_to_a_full_run(tmp_path):
    g = str(tmp_path / "Show.json")
    open(ac.path_for(g), "w").write("{not json")
    assert ac.load(g) == {}


def test_save_never_raises_on_an_unwritable_path():
    assert ac.save("/nonexistent/dir/Show.json", {"a": {"B": {"same_entity": True, "confidence": "high"}}}) is False


# --- a transient failure is not an adjudication ---------------------------------------


def test_an_unavailable_result_is_not_memoised():
    """R-3. `adjudicate_merge` returns the same negative shape for a raising backend, an
    empty response and an unparseable one as it does for a real answer. This cache has no
    TTL and no invalidation, so storing one would answer `escalation_for` forever and
    `escalate`'s `if not adj` would never ask the LLM again -- one transient outage
    stranding the pair permanently."""
    cache = {}
    ac.remember_escalation(cache, "Dothamingo", "Doflamingo",
                                      {"same_entity": False, "confidence": "none", "unavailable": True})
    assert cache == {}, "nothing stored"
    assert ac.escalation_for(cache, "Dothamingo", "Doflamingo") is None, "so the next run retries"


def test_a_genuine_none_confidence_answer_is_still_cached():
    """The boundary. A PARSED answer whose confidence is "none" is a real adjudication --
    the model looked and was unsure -- and is worth not paying for twice. Only the
    unavailable marker is dropped."""
    cache = {}
    ac.remember_escalation(cache, "Dothamingo", "Doflamingo",
                                      {"same_entity": False, "confidence": "none"})
    assert ac.escalation_for(cache, "Dothamingo", "Doflamingo") == {
        "same_entity": False, "confidence": "none"
    }


def test_the_unavailable_marker_never_reaches_the_stored_entry():
    """Even for an answer that IS cached, the marker is a transport detail and must not be
    written into the store, where a later reader would have to know what it means."""
    cache = {}
    ac.remember_escalation(cache, "v", "c", {"same_entity": True, "confidence": "high"})
    assert set(cache["v"]["c"]) == {"same_entity", "confidence"}
