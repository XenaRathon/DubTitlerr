import json

import pytest

import glossary_acquire as ga


def test_normalize_title_strips_disambiguator_and_subpage():
    assert ga.normalize_title("Misty (anime)") == "Misty"
    assert ga.normalize_title("Ash Ketchum/Sun & Moon") == "Ash Ketchum"
    assert ga.normalize_title("Satoshi (PMZ)") == "Satoshi"
    assert ga.normalize_title("Shirahoshi") == "Shirahoshi"


def test_reduce_form_drops_spacing_and_punctuation():
    assert ga.reduce_form("Van der Decken") == "vanderdecken"
    assert ga.reduce_form("Kin" + chr(0x2019) + "emon") == "kinemon"
    assert ga.reduce_form("Kin" + chr(0x27) + "emon") == "kinemon"
    assert ga.reduce_form("Portgas D. Ace") == "portgasd.ace"


@pytest.mark.parametrize("k,n,expected", [
    (56, 58, 0.883),   # Shirahoshi vs Syrahose -- applies
    (21, 37, 0.409),   # Smoker vs Smokey -- legitimate nickname, must NOT apply
    (8, 29, 0.147),    # Decken vs Deccan -- correct form is the minority, flagged
    (5, 6, 0.436),     # thin evidence clears 5:1 but must NOT apply
    (0, 12, 0.0),      # canonical never seen -- handled by the escape clause, not here
])
def test_wilson_lower_matches_spec_values(k, n, expected):
    assert ga.wilson_lower(k, n) == pytest.approx(expected, abs=0.001)


def test_wilson_lower_of_empty_cluster_is_zero():
    assert ga.wilson_lower(0, 0) == 0.0


def _write_conf(tmp_path, name, texts):
    p = tmp_path / f"{name}.dubtitles.conf.json"
    p.write_text(json.dumps([{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]))
    return p


def test_harvest_counts_capitalised_tokens_and_tracks_midsentence(tmp_path):
    _write_conf(tmp_path, "Ep01", ["I saw Shirahoshi today.", "Shirahoshi ran away."])
    counts, mid, n = ga.harvest(str(tmp_path))
    assert n == 1
    assert counts["Shirahoshi"] == 2
    assert "Shirahoshi" in mid          # mid-sentence in the first line


def test_harvest_falls_back_to_srt_when_conf_is_gone(tmp_path):
    (tmp_path / "Ep02.eng.dubtitles.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nWe fought Vergo here.\n\n")
    counts, mid, n = ga.harvest(str(tmp_path))
    assert n == 1
    assert counts["Vergo"] == 1


def test_harvest_prefers_conf_over_srt_for_the_same_episode(tmp_path):
    _write_conf(tmp_path, "Ep03", ["Caesar laughed."])
    (tmp_path / "Ep03.eng.dubtitles.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nMonet laughed.\n\n")
    counts, _mid, n = ga.harvest(str(tmp_path))
    assert n == 1
    assert counts.get("Caesar") == 1 and "Monet" not in counts


@pytest.mark.parametrize("variant,canonical", [
    ("Warlords", "Seven Warlords of the Sea"),
    ("Vander", "Van der Decken"),
    ("Hoshi", "Shirahoshi"),
    ("Ace", "Portgas D. Ace"),
])
def test_is_expansion_rejects_growing_a_token_into_a_phrase(variant, canonical):
    assert ga.is_expansion(variant, canonical) is True


@pytest.mark.parametrize("variant,canonical", [
    ("Syrahose", "Shirahoshi"),
    ("Deccan", "Decken"),
    ("Brooke", "Brook"),
    ("Kinemon", "Kin'emon"),
    ("Vanderdecken", "Van der Decken"),
])
def test_is_expansion_allows_genuine_respellings(variant, canonical):
    assert ga.is_expansion(variant, canonical) is False


def test_similarity_floor_admits_every_true_pair():
    for a, b in [("Syrahose", "Shirahoshi"), ("Deccan", "Decken"),
                 ("Hirohoshi", "Shirahoshi"), ("Brooke", "Brook"),
                 ("Kinemon", "Kin'emon"), ("Momonoske", "Momonosuke")]:
        assert ga.similarity(a, b) >= ga.MIN_SIM, f"{a}/{b} would be dropped"


def test_similarity_rejects_unrelated_names():
    assert ga.similarity("Robin", "Brook") < ga.MIN_SIM
    assert ga.similarity("Monet", "Momonosuke") < ga.MIN_SIM


def test_best_title_picks_the_closest_normalised_title():
    titles = ["Shirahoshi", "Hody Jones", "Neptune (character)", "Van der Decken"]
    name, score = ga.best_title("Syrahose", titles)
    assert name == "Shirahoshi" and score >= ga.MIN_SIM


def test_best_title_strips_the_disambiguator_from_what_it_returns():
    name, _score = ga.best_title("Neptune", ["Neptune (character)"])
    assert name == "Neptune"


def test_best_title_returns_empty_when_nothing_is_close():
    name, score = ga.best_title("Surrender", ["Shirahoshi", "Hody Jones"])
    assert name == "" and score == 0.0


# --- perf refactor: the precomputed title index must agree with best_title's original
# per-call implementation byte-for-byte, since propose()/unmatched() now always go
# through it. These pin that equivalence directly rather than only through propose().

@pytest.mark.parametrize("token,titles", [
    ("Syrahose", ["Shirahoshi", "Hody Jones", "Neptune (character)", "Van der Decken"]),
    ("Neptune", ["Neptune (character)"]),
    ("Surrender", ["Shirahoshi", "Hody Jones"]),
    ("Deccan", ["Decken", "Shirahoshi"]),
    ("Vanderdecken", ["Van der Decken", "Shirahoshi"]),
])
def test_best_title_indexed_agrees_with_best_title_on_a_fixture(token, titles):
    index = ga._title_index(titles)
    assert ga._best_title_indexed(token, index) == ga.best_title(token, titles)


def test_title_index_drops_titles_whose_reduced_form_is_empty():
    # "-" reduces to "" (reduce_form strips hyphens): such a title can never win (similarity
    # returns 0.0 for it, below MIN_SIM), so the index drops it -- fewer entries, same result.
    titles = ["-", "Shirahoshi"]
    index = ga._title_index(titles)
    assert [n for n, *_ in index] == ["Shirahoshi"]
    assert ga._best_title_indexed("Syrahose", index) == ga.best_title("Syrahose", titles)


def test_title_index_collapses_duplicate_normalised_titles():
    # Two disambiguated articles for the same name normalise identically; every extra
    # occurrence would score identically to the first, so only one entry is kept.
    titles = ["Neptune (character)", "Neptune (anime)", "Shirahoshi"]
    index = ga._title_index(titles)
    assert [n for n, *_ in index] == ["Neptune", "Shirahoshi"]
    assert ga._best_title_indexed("Surrender", index) == ga.best_title("Surrender", titles)


def test_decide_applies_a_lopsided_mishearing():
    d = ga.decide("Syrahose", 2, "Shirahoshi", 56, 0.755, True)
    assert d["verdict"] == "apply" and d["bound"] == pytest.approx(0.883, abs=0.001)


def test_decide_applies_when_the_canonical_never_appears():
    # Whisper said 'Kinemon' 12x and 'Kin'emon' never. Wilson is 0.0; the escape clause carries it.
    d = ga.decide("Kinemon", 12, "Kin'emon", 0, 0.90, True)
    assert d["verdict"] == "apply" and d["reason"] == "canonical-unseen"


def test_decide_flags_a_legitimate_nickname():
    d = ga.decide("Smokey", 16, "Smoker", 21, 0.933, True)
    assert d["verdict"] == "flag" and d["reason"] == "share-too-close"


def test_decide_flags_when_the_correct_form_is_the_minority():
    # Deccan 21 vs Decken 8 -- motivates the spec but is NOT auto-fixable; same shape as Smokey.
    d = ga.decide("Deccan", 21, "Decken", 8, 0.844, True)
    assert d["verdict"] == "flag" and d["reason"] == "share-too-close"


def test_decide_marks_a_short_form_of_a_title_as_known():
    d = ga.decide("Yuji", 40, "Yuji Itadori", 0, 0.80, True)
    assert d["verdict"] == "known" and d["reason"] == "short-form"


def test_decide_marks_a_phrase_component_as_known_too():
    # Same relationship as Yuji/Yuji Itadori -- leave the dialogue alone either way.
    d = ga.decide("Warlords", 10, "Seven Warlords of the Sea", 0, 0.80, True)
    assert d["verdict"] == "known" and d["reason"] == "short-form"


def test_decide_flags_below_the_frequency_floor():
    d = ga.decide("Vergo", 2, "Vergo", 0, 1.0, True)
    assert d["verdict"] == "flag" and d["reason"] == "below-floor"


def test_decide_flags_a_token_never_seen_mid_sentence():
    d = ga.decide("Surrender", 22, "Surrender", 0, 1.0, False)
    assert d["verdict"] == "flag" and d["reason"] == "sentence-initial-only"


def test_decide_is_a_noop_when_variant_already_equals_canonical():
    d = ga.decide("Shirahoshi", 56, "Shirahoshi", 56, 1.0, True)
    assert d["verdict"] == "flag" and d["reason"] == "already-canonical"


def test_propose_emits_one_proposal_per_variant_with_the_canonical_count(monkeypatch):
    monkeypatch.setattr(ga.glossary, "is_english", lambda w: False)
    titles = ["Shirahoshi", "Hody Jones"]
    counts = {"Shirahoshi": 56, "Syrahose": 2, "Hirohoshi": 1, "Hody": 9}
    mid = {"Shirahoshi", "Syrahose", "Hirohoshi", "Hody"}
    props = ga.propose(counts, mid, titles)
    by_variant = {p["variant"]: p for p in props}
    assert by_variant["Syrahose"]["canonical"] == "Shirahoshi"
    assert by_variant["Syrahose"]["canonical_count"] == 56
    assert by_variant["Syrahose"]["verdict"] == "apply"
    # Hirohoshi (1) + Shirahoshi (56) clears the floor as a cluster, and Wilson(56, 57)
    # clears dominance -- amended from the brief, whose test predates the cluster-total floor.
    assert by_variant["Hirohoshi"]["verdict"] == "apply"
    assert by_variant["Hirohoshi"]["reason"] == "dominant"


def test_resolve_tokens_does_not_prefilter_below_floor_variants(monkeypatch):
    # Perf refactor pin: R6's floor gate is on variant_count + canonical_count, not
    # variant_count alone, so _resolve_tokens must still resolve a token whose OWN count
    # (1) is below MIN_COUNT -- dropping it early would silently turn this cluster's
    # "apply"/"dominant" verdict into a wrongly-skipped "below-floor" one.
    monkeypatch.setattr(ga.glossary, "is_english", lambda w: False)
    titles = ["Shirahoshi", "Hody Jones"]
    counts = {"Shirahoshi": 56, "Syrahose": 2, "Hirohoshi": 1, "Hody": 9}
    resolved = ga._resolve_tokens(counts, titles)
    assert resolved["Hirohoshi"][0] == "Shirahoshi" and resolved["Hirohoshi"][1] >= ga.MIN_SIM
    assert "Syrahose" in resolved


def test_propose_and_unmatched_agree_whether_resolved_is_shared_or_recomputed(monkeypatch):
    # Perf refactor pin: acquire() now computes _resolve_tokens() once and passes it to
    # both propose() and unmatched(); the shared-resolved call must produce exactly what
    # each function's own from-scratch (resolved=None) call would have.
    monkeypatch.setattr(ga.glossary, "is_english", lambda w: False)
    titles = ["Shirahoshi", "Hody Jones"]
    counts = {"Shirahoshi": 56, "Syrahose": 2, "Hirohoshi": 1, "Hody": 9, "Maybe": 20}
    mid = {"Shirahoshi", "Syrahose", "Hirohoshi", "Hody", "Maybe"}
    resolved = ga._resolve_tokens(counts, titles)
    assert ga.propose(counts, mid, titles, resolved=resolved) == ga.propose(counts, mid, titles)
    assert ga.unmatched(counts, mid, titles, resolved=resolved) == ga.unmatched(counts, mid, titles)
    assert ga.unmatched(counts, mid, titles) == ["Maybe"]        # never resolves -> tier B


def test_propose_ignores_tokens_that_match_no_title():
    props = ga.propose({"Surrender": 22, "Maybe": 20}, {"Surrender", "Maybe"}, ["Shirahoshi"])
    assert props == []


def test_propose_flags_an_ordinary_english_word(monkeypatch):
    monkeypatch.setattr(ga.glossary, "is_english", lambda w: w == "name")
    props = ga.propose({"Name": 9, "Nami": 50}, {"Name", "Nami"}, ["Nami"])
    by = {p["variant"]: p for p in props}
    assert by["Name"]["verdict"] == "flag"
    assert by["Name"]["reason"] == "english-word"
    assert by["Name"]["bound"] == 0.0


def test_apply_proposals_writes_hard_fixes_and_provenance():
    gloss = {"show": "One Pace", "names": ["Luffy"], "hard_fixes": {"zolo": "Zoro"}}
    props = [{"variant": "Syrahose", "canonical": "Shirahoshi", "variant_count": 2,
              "canonical_count": 56, "score": 0.755, "verdict": "apply",
              "reason": "dominant", "bound": 0.883}]
    g = ga.apply_proposals(gloss, props, run_id="run1")
    assert g["hard_fixes"]["Syrahose"] == "Shirahoshi"
    assert g["hard_fixes"]["zolo"] == "Zoro"          # curated entries preserved
    assert g["acquired"]["Syrahose"]["canonical"] == "Shirahoshi"
    assert g["acquired"]["Syrahose"]["run"] == "run1"
    assert gloss.get("acquired") is None               # input not mutated


def test_apply_proposals_records_flagged_with_its_reason():
    props = [{"variant": "Smokey", "canonical": "Smoker", "variant_count": 16,
              "canonical_count": 21, "score": 0.933, "verdict": "flag",
              "reason": "share-too-close", "bound": 0.409}]
    g = ga.apply_proposals({"show": "One Pace"}, props, run_id="run1")
    assert "Smokey" not in g.get("hard_fixes", {})
    assert g["flagged"]["Smokey"]["reason"] == "share-too-close"
    assert g["flagged"]["Smokey"]["canonical"] == "Smoker"


def test_apply_proposals_records_known_and_never_flags_it():
    props = [{"variant": "Yuji", "canonical": "Yuji Itadori", "variant_count": 40,
              "canonical_count": 0, "score": 0.8, "verdict": "known",
              "reason": "short-form", "bound": 0.0}]
    g = ga.apply_proposals({"show": "JJK"}, props, run_id="run1")
    assert g["known"] == ["Yuji"]
    assert "Yuji" not in g.get("flagged", {})
    assert "Yuji" not in g.get("hard_fixes", {})


def test_apply_proposals_never_adds_acquired_names_to_the_initial_prompt():
    gloss = {"show": "One Pace", "names": ["Luffy"], "initial_prompt": "Spell names correctly: Luffy."}
    props = [{"variant": "Syrahose", "canonical": "Shirahoshi", "variant_count": 2,
              "canonical_count": 56, "score": 0.755, "verdict": "apply",
              "reason": "dominant", "bound": 0.883}]
    g = ga.apply_proposals(gloss, props, run_id="run1")
    assert "Shirahoshi" not in g["initial_prompt"]
    assert "Shirahoshi" not in g["names"]


def test_revert_removes_only_acquired_entries():
    gloss = {"hard_fixes": {"zolo": "Zoro", "Syrahose": "Shirahoshi"},
             "acquired": {"Syrahose": {"canonical": "Shirahoshi", "run": "run1"}}}
    g = ga.revert(gloss)
    assert g["hard_fixes"] == {"zolo": "Zoro"}
    assert g.get("acquired", {}) == {}


def test_revert_can_target_a_single_run():
    gloss = {"hard_fixes": {"a": "A", "b": "B"},
             "acquired": {"a": {"canonical": "A", "run": "run1"},
                          "b": {"canonical": "B", "run": "run2"}}}
    g = ga.revert(gloss, run_id="run1")
    assert g["hard_fixes"] == {"b": "B"}
    assert list(g["acquired"]) == ["b"]


def test_revert_leaves_a_hard_fix_a_human_has_since_changed():
    gloss = {"hard_fixes": {"Syrahose": "SomethingElse"},
             "acquired": {"Syrahose": {"canonical": "Shirahoshi", "run": "run1"}}}
    g = ga.revert(gloss)
    assert g["hard_fixes"]["Syrahose"] == "SomethingElse"


def test_acquire_is_a_noop_when_the_wiki_cannot_be_resolved(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    # harvest-first short-circuit means resolve_wiki is only reached once there is
    # something to score -- give it a token so this test actually exercises that call.
    _write_conf(tmp_path, "Ep01", ["I saw Shirahoshi today."] * 5)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: None)
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["note"] == "wiki unresolved"
    assert json.loads(gp.read_text()) == {"show": "One Pace"}


def test_acquire_skips_the_wiki_entirely_when_nothing_was_harvested(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    called = []
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: called.append(1) or "https://x/api.php")
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["note"] == "nothing harvested"
    assert called == []


def test_acquire_dry_run_does_not_write(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    # NOTE: brief's literal fixture (Syrahose x60 vs Shirahoshi x20) makes the VARIANT
    # dominate the CANONICAL, which R3 (dominance) correctly flags rather than applies --
    # verified against decide()/wilson_lower directly. Swapped to mirror the 56-vs-2 case
    # from test_wilson_lower_matches_spec_values / test_propose_emits_one_proposal_..., which
    # is the shape the design doc's dominance rule actually applies on. See task-10-report.md.
    _write_conf(tmp_path, "Ep01", ["I saw Shirahoshi today."] * 56 + ["I fear Syrahose."] * 2)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["applied"] == 1
    assert json.loads(gp.read_text()) == {"show": "One Pace"}   # untouched


def test_acquire_never_escalates_a_gate_failure_to_the_llm(tmp_path, monkeypatch):
    calls = []
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["Hey Smokey.", "Smokey again.", "Smokey thrice.",
                                   "Smoker is here.", "Smoker again.", "Smoker thrice.",
                                   "Smoker once more."] * 6)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Smoker"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: calls.append(a) or {"canonical": "", "confidence": "none", "dub_note": ""})
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["applied"] == 0
    assert calls == []      # matched a title then failed R3 -> flagged, never adjudicated


def test_acquire_reports_titles_failure_without_raising(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    orig = json.dumps({"show": "One Pace"})
    gp.write_text(orig)
    _write_conf(tmp_path, "Ep01", ["I saw Shirahoshi today."] * 56 + ["I fear Syrahose."] * 2)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")

    def boom(*a, **k):
        raise RuntimeError("wiki down")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", boom)
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["note"].startswith("titles-failed")
    assert gp.read_text() == orig


def test_acquire_write_failure_leaves_original_glossary_intact(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    orig = json.dumps({"show": "One Pace"})
    gp.write_text(orig)
    _write_conf(tmp_path, "Ep01", ["I saw Shirahoshi today."] * 56 + ["I fear Syrahose."] * 2)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])

    def boom(*a, **k):
        raise TypeError("not serializable")
    monkeypatch.setattr(ga.json, "dump", boom)
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["note"].startswith("write-failed")
    assert json.loads(gp.read_text()) == {"show": "One Pace"}
    assert not (tmp_path / "One Pace.json.tmp").exists()


def test_acquire_run_id_differs_when_title_content_differs(tmp_path, monkeypatch):
    # "Syrahose" alone (never harvested as "Shirahoshi"/"Shirahoshy") hits the
    # canonical-unseen escape clause, so both runs apply -- only the matched canonical
    # spelling differs between them, same title COUNT (1) either way.
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    texts = ["I fear Syrahose."] * 5
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir(); dir_b.mkdir()
    _write_conf(dir_a, "Ep01", texts)
    _write_conf(dir_b, "Ep01", texts)
    gp_a, gp_b = dir_a / "One Pace.json", dir_b / "One Pace.json"
    gp_a.write_text(json.dumps({"show": "One Pace"}))
    gp_b.write_text(json.dumps({"show": "One Pace"}))
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    ga.acquire(str(gp_a), str(dir_a), apply=True)
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshy"])
    ga.acquire(str(gp_b), str(dir_b), apply=True)
    run_a = json.loads(gp_a.read_text())["acquired"]["Syrahose"]["run"]
    run_b = json.loads(gp_b.read_text())["acquired"]["Syrahose"]["run"]
    assert run_a != run_b


def test_unmatched_lists_frequent_tokens_with_no_title_match():
    counts = {"Shirahoshi": 56, "Zunesha": 7, "Maybe": 20}
    mid = {"Shirahoshi", "Zunesha", "Maybe"}
    out = ga.unmatched(counts, mid, ["Shirahoshi", "Maybe"])
    assert out == ["Zunesha"]


def test_unmatched_respects_the_frequency_floor():
    assert ga.unmatched({"Zunesha": 2}, {"Zunesha"}, ["Shirahoshi"]) == []


def test_acquire_reports_tier_b_adjudications(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    # NOTE: brief's literal fixture puts "Zunesha" sentence-initial in every line, so it never
    # enters `midsentence` (see mine_glossary.mine_text) and unmatched() -- which gates on
    # midsentence exactly like decide() does for tier A -- would never see it. Reworded so the
    # token is genuinely mid-sentence. See task-11-report.md.
    # C1: tier B's canonical is now re-validated against the title set, so the fixture must
    # use a genuine dub-rename pair (like the spec's own Kasumi/Misty example) -- similarity
    # is too low for tier A to catch it (0.456 < MIN_SIM), but it is a real, comparable-length
    # title, so it clears the tier-B R1+R2 check. Using "Zunisha" here (near-identical to
    # "Zunesha") would let tier A resolve it directly and the test would never reach tier B
    # at all -- see the C1 rejection test below for the case where the canonical is invalid.
    _write_conf(tmp_path, "Ep01", ["I saw Kasumi walk.", "I saw Kasumi again.", "I saw Kasumi thrice."] * 3)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi", "Misty"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: {"canonical": "Misty", "confidence": "high", "dub_note": "dub"})
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["tier_b"] == {"Kasumi": "Misty"}


def test_c1_acquire_rejects_a_tier_b_canonical_that_is_not_a_real_wiki_title(tmp_path, monkeypatch):
    # C1 reproduction: the reviewer's exact scenario. adjudicate() returns free-form model
    # text carrying a parenthetical -- never a real title on this wiki -- and it must NOT
    # become the tier_b canonical (which apply=True would otherwise write into flagged as
    # an accept-able fix, and a human 'y' would then send straight to hard_fixes).
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["I saw Zunesha walk.", "I saw Zunesha again.", "I saw Zunesha thrice."] * 3)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: {"canonical": "Zou Elephant (Zunisha)", "confidence": "high", "dub_note": ""})
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["tier_b"] == {"Zunesha": ""}
    g = json.loads(gp.read_text())
    assert g["flagged"]["Zunesha"]["canonical"] == ""
    assert "Zou Elephant" not in json.dumps(g)
    # and a human 'y' on this entry must not turn it into a hard_fix either (record_decision's
    # own defence-in-depth, exercised directly in test_record_decision_... below).


def test_context_lines_returns_real_lines_per_token(tmp_path):
    _write_conf(tmp_path, "Ep01", ["Hey Smokey.", "Smoker is here.", "Nothing relevant."])
    ctx = ga.context_lines(str(tmp_path), ["Smokey", "Smoker"])
    assert ctx["Smokey"] == ["Hey Smokey."]
    assert ctx["Smoker"] == ["Smoker is here."]


def test_context_lines_caps_at_the_limit(tmp_path):
    _write_conf(tmp_path, "Ep01", ["Smokey one.", "Smokey two.", "Smokey three."])
    ctx = ga.context_lines(str(tmp_path), ["Smokey"], limit=2)
    assert len(ctx["Smokey"]) == 2


def test_context_lines_matches_whole_words_only(tmp_path):
    _write_conf(tmp_path, "Ep01", ["Shirahoshi waited."])
    ctx = ga.context_lines(str(tmp_path), ["Hoshi"])
    assert ctx["Hoshi"] == []


def test_build_merge_prompt_quotes_both_sets_of_lines():
    pr = ga.build_merge_prompt("Deccan", "Decken", ["after Deccan."], ["Van Der Decken is coming."], "One Pace")
    assert "after Deccan." in pr and "Van Der Decken is coming." in pr
    assert "One Pace" in pr


def test_adjudicate_merge_parses_a_merge_verdict(monkeypatch):
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: '{"same_entity": true, "confidence": "high"}')
    out = ga.adjudicate_merge("Deccan", "Decken", ["x"], ["y"], "One Pace")
    assert out == {"same_entity": True, "confidence": "high"}


def test_adjudicate_merge_is_a_noop_when_the_llm_is_down(monkeypatch):
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: "")
    assert ga.adjudicate_merge("a", "b", ["x"], ["y"], "S") == {"same_entity": False, "confidence": "none"}


@pytest.mark.parametrize("raw,expect_merge", [
    ('{"same_entity": true, "confidence": "high"}', True),
    ('{"same_entity": false, "confidence": "high"}', False),
    ('{"same_entity": "no", "confidence": "high"}', False),
    ('{"same_entity": "false", "confidence": "high"}', False),
    ('{"same_entity": "true", "confidence": "high"}', False),
    ('{"same_entity": 1, "confidence": "high"}', False),
])
def test_adjudicate_merge_requires_a_literal_boolean(monkeypatch, raw, expect_merge):
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: raw)
    assert ga.adjudicate_merge("Smokey", "Smoker", ["x"], ["y"], "S")["same_entity"] is expect_merge


def test_tier_c_runs_only_for_share_too_close(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(ga, "adjudicate_merge",
                        lambda v, c, cv, cc, s: seen.append(v) or {"same_entity": True, "confidence": "high"})
    props = [{"variant": "Deccan", "canonical": "Decken", "variant_count": 21, "canonical_count": 8,
              "score": 0.844, "verdict": "flag", "reason": "share-too-close", "bound": 0.147},
             {"variant": "Warlords", "canonical": "Seven Warlords of the Sea", "variant_count": 10,
              "canonical_count": 0, "score": 0.8, "verdict": "known", "reason": "short-form", "bound": 0.0}]
    out = ga.escalate(props, {"Deccan": ["after Deccan."], "Decken": ["Van Der Decken."]}, "One Pace")
    assert seen == ["Deccan"]                       # the short-form case never escalates
    assert out[0]["verdict"] == "apply" and out[0]["reason"] == "context-merged"


def test_acquire_report_counts_apply_known_and_flag_separately(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    monkeypatch.setattr(ga, "propose", lambda *a, **k: [
        {"variant": "Syrahose", "canonical": "Shirahoshi", "variant_count": 2, "canonical_count": 56,
         "score": 0.9, "verdict": "apply", "reason": "dominant", "bound": 0.9},
        {"variant": "Ace", "canonical": "Portgas D. Ace", "variant_count": 5, "canonical_count": 0,
         "score": 0.8, "verdict": "known", "reason": "short-form", "bound": 0.0},
        {"variant": "Maybe", "canonical": "Nami", "variant_count": 4, "canonical_count": 1,
         "score": 0.75, "verdict": "flag", "reason": "english-word", "bound": 0.0},
    ])
    _write_conf(tmp_path, "Ep01", ["I saw Something today."])
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["applied"] == 1 and rep["known"] == 1 and rep["flagged"] == 1


def test_review_items_normalises_legacy_string_entries():
    gloss = {"flagged": {"Yuji": "no-match",
                         "Deccan": {"reason": "share-too-close", "canonical": "Decken",
                                    "context": ["after Deccan."]}}}
    items = {i["term"]: i for i in ga.review_items(gloss)}
    assert items["Yuji"]["reason"] == "no-match" and items["Yuji"]["context"] == []
    assert items["Deccan"]["canonical"] == "Decken"


def test_record_decision_accept_writes_the_fix_and_clears_the_flag():
    gloss = {"flagged": {"Deccan": {"reason": "share-too-close", "canonical": "Decken"}}}
    g = ga.record_decision(gloss, "Deccan", accept=True)
    assert g["hard_fixes"]["Deccan"] == "Decken"
    assert "Deccan" not in g.get("flagged", {})
    assert g["acquired"]["Deccan"]["reason"] == "human-approved"


def test_record_decision_reject_marks_it_known_so_it_is_never_asked_again():
    gloss = {"flagged": {"Smokey": {"reason": "share-too-close", "canonical": "Smoker"}}}
    g = ga.record_decision(gloss, "Smokey", accept=False)
    assert g["known"] == ["Smokey"]
    assert "Smokey" not in g.get("flagged", {})
    assert "Smokey" not in g.get("hard_fixes", {})


def test_acquire_apply_persists_tier_b_into_flagged_as_no_wiki_match(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    orig = json.dumps({"show": "One Pace"})
    gp.write_text(orig)
    # See the C1 note on test_acquire_reports_tier_b_adjudications: Kasumi/Misty is a
    # genuine dub-rename pair tier A cannot catch, so this exercises the real tier-B path.
    _write_conf(tmp_path, "Ep01", ["I saw Kasumi walk.", "I saw Kasumi again.", "I saw Kasumi thrice."] * 3)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi", "Misty"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: {"canonical": "Misty", "confidence": "high", "dub_note": "dub"})
    ga.acquire(str(gp), str(tmp_path), apply=False)
    assert gp.read_text() == orig                        # dry run never writes tier_b either
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["tier_b"] == {"Kasumi": "Misty"}
    g = json.loads(gp.read_text())
    assert g["flagged"]["Kasumi"]["reason"] == "no-wiki-match"
    assert g["flagged"]["Kasumi"]["canonical"] == "Misty"
    assert "I saw Kasumi walk." in g["flagged"]["Kasumi"]["context"]


def test_record_decision_accept_clears_a_stale_known_entry():
    gloss = {"known": ["Deccan"], "flagged": {"Deccan": {"canonical": "Decken"}}}
    g = ga.record_decision(gloss, "Deccan", accept=True)
    assert g["hard_fixes"]["Deccan"] == "Decken"
    assert "Deccan" not in g.get("known", [])
    assert "Deccan" not in g.get("flagged", {})


def test_record_decision_reject_clears_a_stale_hard_fix():
    gloss = {"hard_fixes": {"Deccan": "Decken"}, "flagged": {"Deccan": {"canonical": "Decken2"}}}
    g = ga.record_decision(gloss, "Deccan", accept=False)
    assert g["known"] == ["Deccan"]
    assert "Deccan" not in g.get("hard_fixes", {})
    assert "Deccan" not in g.get("acquired", {})
    assert "Deccan" not in g.get("flagged", {})


def test_main_review_asks_a_real_question_for_a_legacy_no_canonical_entry(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"flagged": {"Yuji": "no-match"}}))
    monkeypatch.setattr("sys.argv", ["glossary_acquire.py", str(gp), str(tmp_path), "--review", "--apply"])
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return "y"
    monkeypatch.setattr("builtins.input", fake_input)
    ga.main()
    assert any("no fix proposed" in p for p in prompts)
    g = json.loads(gp.read_text())
    assert g["known"] == ["Yuji"]
    assert "Yuji" not in g.get("flagged", {})


def test_main_review_leaving_a_legacy_entry_pending_is_a_no_op(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    orig = json.dumps({"flagged": {"Yuji": "no-match"}})
    gp.write_text(orig)
    monkeypatch.setattr("sys.argv", ["glossary_acquire.py", str(gp), str(tmp_path), "--review", "--apply"])
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    ga.main()
    g = json.loads(gp.read_text())
    assert g["flagged"]["Yuji"] == "no-match"       # untouched: still pending, never dropped


# --- final-fix-brief.md: C1, C2, C3, I3, I4, I5, R4, R6e ---------------------------------

def test_c1_record_decision_refuses_a_canonical_that_is_not_a_bare_wiki_title():
    # Reproduction: a hand-edited/legacy flagged entry carries a disambiguator R1 exists to
    # strip. Even a human 'y' must not turn this into a hard_fix -- defence in depth for
    # the path record_decision cannot check against `titles` directly.
    gloss = {"flagged": {"Zunesha": {"reason": "no-wiki-match", "canonical": "Zou Elephant (Zunisha)"}}}
    g = ga.record_decision(gloss, "Zunesha", accept=True)
    assert "Zunesha" not in g.get("hard_fixes", {})
    assert g["flagged"]["Zunesha"]["reason"] == "unsafe-canonical-rejected"


def test_c1_record_decision_refuses_an_expansion_even_on_accept():
    gloss = {"flagged": {"Ace": {"reason": "no-wiki-match", "canonical": "Portgas D. Ace"}}}
    g = ga.record_decision(gloss, "Ace", accept=True)
    assert "Ace" not in g.get("hard_fixes", {})
    assert g["flagged"]["Ace"]["reason"] == "unsafe-canonical-rejected"


def test_c1_record_decision_still_accepts_a_safe_canonical():
    gloss = {"flagged": {"Deccan": {"reason": "share-too-close", "canonical": "Decken"}}}
    g = ga.record_decision(gloss, "Deccan", accept=True)
    assert g["hard_fixes"]["Deccan"] == "Decken"
    assert "Deccan" not in g.get("flagged", {})


def test_c2_propose_skips_a_settled_variant_entirely():
    # A human already rejected 'Smokey' via --review, so it is in `known`. Even though the
    # counts would otherwise dominate it into an 'apply', settled must suppress it -- no
    # proposal at all, not even a flag.
    counts = {"Smokey": 56, "Smoker": 2}
    mid = {"Smokey", "Smoker"}
    props = ga.propose(counts, mid, ["Smoker"], settled={"Smokey"})
    assert [p["variant"] for p in props] == []


def test_c2_propose_positional_call_still_works_without_settled():
    props = ga.propose({"Syrahose": 2, "Shirahoshi": 56}, {"Syrahose", "Shirahoshi"}, ["Shirahoshi"])
    assert any(p["variant"] == "Syrahose" for p in props)


def test_c2_acquire_never_reapplies_a_hard_fix_a_human_rejected(tmp_path, monkeypatch):
    # End-to-end reproduction of the brief's "rejected-then-reapplied" bug: a human said 'n'
    # on Smokey->Smoker (it landed in `known`); an unattended --apply sweep must not revert
    # that by writing hard_fixes['Smokey'] on the next run.
    gp = tmp_path / "One Pace.json"
    orig = json.dumps({"show": "One Pace", "known": ["Smokey"]})
    gp.write_text(orig)
    _write_conf(tmp_path, "Ep01", ["Hey Smokey."] * 16 + ["We saw Smoker today."] * 21)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Smoker"])
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["proposed"] == 0     # settled suppressed Smokey; Smoker==canonical is a no-op
    assert gp.read_text() == orig   # nothing to write -> original untouched
    g = json.loads(gp.read_text())
    assert "Smokey" not in g.get("hard_fixes", {})
    assert g.get("known") == ["Smokey"]


def test_c2_apply_proposals_clears_a_stale_known_when_verdict_flips_to_apply():
    gloss = {"known": ["Syrahose"]}
    props = [{"variant": "Syrahose", "canonical": "Shirahoshi", "variant_count": 2, "canonical_count": 56,
              "score": 0.9, "verdict": "apply", "reason": "dominant", "bound": 0.9}]
    g = ga.apply_proposals(gloss, props, run_id="run2")
    assert g["hard_fixes"]["Syrahose"] == "Shirahoshi"
    assert "Syrahose" not in g.get("known", [])


def test_c2_apply_proposals_clears_a_stale_hard_fix_when_verdict_flips_to_flag():
    gloss = {"hard_fixes": {"Smokey": "Smoker"}, "acquired": {"Smokey": {"canonical": "Smoker", "run": "old"}}}
    props = [{"variant": "Smokey", "canonical": "Smoker", "variant_count": 16, "canonical_count": 21,
              "score": 0.933, "verdict": "flag", "reason": "share-too-close", "bound": 0.409}]
    g = ga.apply_proposals(gloss, props, run_id="run2")
    assert "Smokey" not in g.get("hard_fixes", {})
    assert "Smokey" not in g.get("acquired", {})
    assert g["flagged"]["Smokey"]["reason"] == "share-too-close"


def test_i3_apply_proposals_clears_a_stale_flagged_entry_on_known():
    gloss = {"flagged": {"Yuji": "no-match"}}
    props = [{"variant": "Yuji", "canonical": "Yuji Itadori", "variant_count": 40, "canonical_count": 0,
              "score": 0.8, "verdict": "known", "reason": "short-form", "bound": 0.0}]
    g = ga.apply_proposals(gloss, props, run_id="run1")
    assert g["known"] == ["Yuji"]
    assert "Yuji" not in g.get("flagged", {})


def test_i4_flagged_proposals_carry_real_context_lines(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["Hey Smokey.", "Smokey again.", "Smokey thrice.",
                                   "Smoker is here.", "Smoker again.", "Smoker thrice.",
                                   "Smoker once more."] * 6)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Smoker"])
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    flagged = [p for p in rep["proposals"] if p["verdict"] == "flag"]
    assert flagged and all(p["context"] for p in flagged)
    g = json.loads(gp.read_text())
    assert g["flagged"]["Smokey"]["context"]        # I4: no longer an empty list


def test_i5_flagged_count_is_not_inflated_by_pre_existing_glossary_entries(tmp_path, monkeypatch):
    # I5 reproduction: a glossary_verify-authored `flagged` entry already on disk must not
    # be folded into acquire()'s reported flagged COUNT once tier_b shares the same dict.
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace", "flagged": {"Preexisting": "low-confidence"}}))
    _write_conf(tmp_path, "Ep01", ["I saw Kasumi walk.", "I saw Kasumi again.", "I saw Kasumi thrice."] * 3)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Misty"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: {"canonical": "Misty", "confidence": "high", "dub_note": ""})
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["flagged"] == 0     # no tier-A flag proposals here -- tier_b/pre-existing must not count
    g = json.loads(gp.read_text())
    assert len(g["flagged"]) == 2  # Preexisting + Kasumi both persisted on disk


def test_r4_revert_exempts_a_human_approved_entry():
    gloss = {"hard_fixes": {"Deccan": "Decken", "Syrahose": "Shirahoshi"},
             "acquired": {"Deccan": {"canonical": "Decken", "run": "review"},
                          "Syrahose": {"canonical": "Shirahoshi", "run": "sweep1"}}}
    g = ga.revert(gloss)
    assert g["hard_fixes"] == {"Deccan": "Decken"}
    assert list(g["acquired"]) == ["Deccan"]


def test_r4_revert_with_a_run_id_still_exempts_review():
    gloss = {"hard_fixes": {"Deccan": "Decken"}, "acquired": {"Deccan": {"canonical": "Decken", "run": "review"}}}
    g = ga.revert(gloss, run_id="review")
    assert g["hard_fixes"] == {"Deccan": "Decken"}


def test_r6e_english_word_gate_demotes_apply_but_not_known(monkeypatch):
    # The interaction the contract calls out: is_english forced True must still let a
    # short-form ('known') verdict pass through untouched -- only 'apply' gets demoted.
    monkeypatch.setattr(ga.glossary, "is_english", lambda w: True)
    props = ga.propose({"Yuji": 40}, {"Yuji"}, ["Yuji Itadori"])
    assert props[0]["verdict"] == "known" and props[0]["reason"] == "short-form"


def test_r6e_english_word_gate_still_demotes_a_real_apply(monkeypatch):
    monkeypatch.setattr(ga.glossary, "is_english", lambda w: True)
    props = ga.propose({"Syrahose": 2, "Shirahoshi": 56}, {"Syrahose", "Shirahoshi"}, ["Shirahoshi"])
    by = {p["variant"]: p for p in props}
    assert by["Syrahose"]["verdict"] == "flag" and by["Syrahose"]["reason"] == "english-word"


def test_c3_write_json_is_atomic_utf8_and_leaves_no_tmp_behind(tmp_path):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"old": True}))
    ga._write_json(str(p), {"show": chr(0x30ab) + chr(0x30bf) + chr(0x30ab) + chr(0x30ca)})
    assert json.loads(p.read_text(encoding="utf-8"))["show"] == chr(0x30ab) + chr(0x30bf) + chr(0x30ab) + chr(0x30ca)
    assert not (tmp_path / "g.json.tmp").exists()


def test_c3_main_revert_reports_rather_than_tracebacks_on_a_malformed_glossary(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text("{not valid json")
    monkeypatch.setattr("sys.argv", ["glossary_acquire.py", str(gp), str(tmp_path), "--revert"])
    ga.main()      # must not raise
    assert gp.read_text() == "{not valid json"


def test_c3_main_review_apply_writes_through_write_json(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"flagged": {"Yuji": "no-match"}}))
    monkeypatch.setattr("sys.argv", ["glossary_acquire.py", str(gp), str(tmp_path), "--review", "--apply"])
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    ga.main()
    assert not (tmp_path / "One Pace.json.tmp").exists()
    assert json.loads(gp.read_text())["known"] == ["Yuji"]


def test_c3_main_revert_apply_writes_through_write_json(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"hard_fixes": {"Syrahose": "Shirahoshi"},
                              "acquired": {"Syrahose": {"canonical": "Shirahoshi", "run": "run1"}}}))
    monkeypatch.setattr("sys.argv", ["glossary_acquire.py", str(gp), str(tmp_path), "--revert", "--apply"])
    ga.main()
    assert not (tmp_path / "One Pace.json.tmp").exists()
    assert json.loads(gp.read_text()).get("hard_fixes", {}) == {}
