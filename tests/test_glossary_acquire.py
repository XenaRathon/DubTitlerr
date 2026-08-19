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


def test_decide_flags_an_expansion():
    d = ga.decide("Warlords", 10, "Seven Warlords of the Sea", 0, 0.80, True)
    assert d["verdict"] == "flag" and d["reason"] == "would-expand"


def test_decide_flags_below_the_frequency_floor():
    d = ga.decide("Vergo", 2, "Vergo", 0, 1.0, True)
    assert d["verdict"] == "flag" and d["reason"] == "below-floor"


def test_decide_flags_a_token_never_seen_mid_sentence():
    d = ga.decide("Surrender", 22, "Surrender", 0, 1.0, False)
    assert d["verdict"] == "flag" and d["reason"] == "sentence-initial-only"


def test_decide_is_a_noop_when_variant_already_equals_canonical():
    d = ga.decide("Shirahoshi", 56, "Shirahoshi", 56, 1.0, True)
    assert d["verdict"] == "flag" and d["reason"] == "already-canonical"
