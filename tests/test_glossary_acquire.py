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
    assert g["flagged"]["Smokey"] == "share-too-close"


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
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: None)
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["note"] == "wiki unresolved"
    assert json.loads(gp.read_text()) == {"show": "One Pace"}


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
    _write_conf(tmp_path, "Ep01", ["I saw Zunesha walk.", "I saw Zunesha again.", "I saw Zunesha thrice."] * 3)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: {"canonical": "Zunisha", "confidence": "high", "dub_note": "dub"})
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["tier_b"] == {"Zunesha": "Zunisha"}
