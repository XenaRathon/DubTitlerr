"""The common-word guard for glossary VERIFY auto-writes (VERIFY_SKIP_COMMON_WORDS=1).

A single-token English word expanded into a longer wiki title is flagged 'common-word' for
review, not silently written.  Opt-in (default off: byte-identical behaviour).  The arc gate
overrides: an English word that IS in the arc universe is written, not flagged."""

import json

import pytest

import glossary
import glossary_verify as gv

# The host's word list decides what glossary.is_english() says (the bundled list is 233 words here, production's image has
# wamerican with ~100k), so no test may depend on it: every test runs against exactly these words.
WORDS = {"government", "castle", "lobby", "elders", "jolly", "world"}


@pytest.fixture(autouse=True)
def english_words(monkeypatch):
    monkeypatch.setattr(glossary, "_WORDS", set(WORDS))


def high(canon):
    return {"canonical": canon, "confidence": "high", "dub_note": ""}


def _gloss(**extra):
    return {
        "show": "One Piece",
        "names": [],
        "phrases": [],
        "hard_fixes": {},
        "initial_prompt": "P",
        **extra,
    }


# ---- guard OFF (default): byte-identical behaviour ---------------------------


def test_guard_off_by_default_english_word_is_written():
    """GUARD: with VERIFY_SKIP_COMMON_WORDS unset, a single English word expansion is written
    exactly as before — the default is byte-identical."""
    g = _gloss(names=["Government"])
    new = gv.apply_results(g, {"Government": high("World Government")})
    assert "World Government" in new["phrases"]
    assert "Government" not in new.get("flagged", {})


def test_guard_off_explicitly(monkeypatch):
    monkeypatch.delenv("VERIFY_SKIP_COMMON_WORDS", raising=False)
    g = _gloss(names=["Castle"])
    new = gv.apply_results(g, {"Castle": high("Drum Castle")})
    assert "Drum Castle" in new["phrases"]


# ---- guard ON: single English word flagged -----------------------------------


def test_guard_on_flags_a_single_english_word_expansion(monkeypatch):
    """The core case: 'Government' -> 'World Government' is flagged 'common-word'."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["Government"])
    new = gv.apply_results(g, {"Government": high("World Government")})
    assert "World Government" not in new["names"] + new["phrases"]
    assert new["flagged"]["Government"] == {"reason": "common-word", "canonical": "World Government"}


# ---- multi-word term is NEVER affected by this guard -------------------------


def test_multi_word_term_unaffected_by_guard(monkeypatch):
    """A multi-word term like 'Straw Hat' is not a single token; the guard does not touch it."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(phrases=["Straw Hat"])
    new = gv.apply_results(g, {"Straw Hat": high("Straw Hat Pirates")})
    assert "Straw Hat Pirates" in new["phrases"]
    assert "Straw Hat" not in new.get("flagged", {})


# ---- non-English single token is unaffected ----------------------------------


def test_non_english_single_token_unaffected(monkeypatch):
    """'Momonosuke' is a single token but not an English word; the guard does not touch it."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["Momonosuke"])
    new = gv.apply_results(g, {"Momonosuke": high("Kouzuki Momonosuke")})
    assert "Kouzuki Momonosuke" in new["phrases"]
    assert "Momonosuke" not in new.get("flagged", {})


# ---- arc-gate override: English word IN the arc universe is written ----------


def test_arc_gate_overrides_common_word_guard(monkeypatch):
    """An English word whose canonical IS in the arc universe is written (the arc evidence wins)."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = _gloss(
        names=["Castle"],
        arc_titles={"Drum Island": ["Drum Castle", "Tony Tony Chopper"]},
    )
    new = gv.apply_results(g, {"Castle": high("Drum Castle")})
    assert "Drum Castle" in new["phrases"]
    assert "Castle" not in new.get("flagged", {})


def test_arc_gate_does_not_override_when_canonical_not_in_universe(monkeypatch):
    """An English word whose canonical is NOT in the arc universe stays flagged 'common-word',
    not 'not-in-arc-pages' — the common-word check runs first."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = _gloss(
        names=["Government"],
        arc_titles={"Drum Island": ["Drum Castle", "Tony Tony Chopper"]},
    )
    new = gv.apply_results(g, {"Government": high("World Government")})
    assert new["flagged"]["Government"]["reason"] == "common-word"


# ---- flagged entry shape equals other flagged reasons ------------------------


def test_flagged_entry_shape_matches_arc_gate_shape(monkeypatch):
    """The 'common-word' flagged entry is a dict with 'reason' and 'canonical', the same shape
    as the 'not-in-arc-pages' flagged entry — not a bare string like low-confidence."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["Lobby"])
    new = gv.apply_results(g, {"Lobby": high("Enies Lobby")})
    entry = new["flagged"]["Lobby"]
    assert isinstance(entry, dict)
    assert set(entry.keys()) == {"reason", "canonical"}
    assert entry["reason"] == "common-word"
    assert entry["canonical"] == "Enies Lobby"


# ---- verify() report counter ------------------------------------------------


def test_verify_report_counts_common_word_blocked(monkeypatch, tmp_path):
    """verify() includes the guard's block count in the report, same style as arc_gate."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    gloss = _gloss(names=["Government", "Momonosuke"])
    path = tmp_path / "g.json"
    path.write_text(json.dumps(gloss))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["World Government", "Kouzuki Momonosuke"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    results = {
        "Government": high("World Government"),
        "Momonosuke": high("Kouzuki Momonosuke"),
    }
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: results[term])
    rep = gv.verify(str(path))
    assert rep["common_word"] == {"blocked": 1}
    assert rep["applied"] == 1  # Momonosuke written, Government blocked


def test_verify_report_has_no_common_word_key_when_guard_off(monkeypatch, tmp_path):
    """GUARD: default report shape has no common_word key."""
    monkeypatch.delenv("VERIFY_SKIP_COMMON_WORDS", raising=False)
    gloss = _gloss(names=["Government", "Momonosuke"])
    path = tmp_path / "g.json"
    path.write_text(json.dumps(gloss))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["World Government", "Kouzuki Momonosuke"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    results = {
        "Government": high("World Government"),
        "Momonosuke": high("Kouzuki Momonosuke"),
    }
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: results[term])
    rep = gv.verify(str(path))
    assert "common_word" not in rep
    assert rep["applied"] == 2


# ---- the word list is the one glossary.is_english loads ----------------------------------------------------------


def test_the_guard_follows_the_word_list_file_and_ignores_case(monkeypatch, tmp_path):
    words = tmp_path / "words"
    words.write_text("castle\n")
    monkeypatch.setattr(glossary, "_WORDS", None)  # reload from the bundled list plus this file
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(words))
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["CASTLE", "Government"])
    new = gv.apply_results(g, {"CASTLE": high("Drum Castle"), "Government": high("World Government")})
    assert new["flagged"] == {"CASTLE": {"reason": "common-word", "canonical": "Drum Castle"}}
    assert "World Government" in new["phrases"]  # not in this list, so not a common word here


def test_a_name_that_is_also_an_english_word_is_flagged_for_review_not_dropped(monkeypatch):
    """The documented cost: a big dictionary holds words that are names in the show (Law, Smoker). The guard flags them for
    review; it never deletes the term or the canonical, and the arc gate can rescue them."""
    monkeypatch.setattr(glossary, "_WORDS", WORDS | {"law"})
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["Law"])
    new = gv.apply_results(g, {"Law": high("Trafalgar D. Water Law")})
    assert new["names"] == ["Law"] and new["flagged"]["Law"]["reason"] == "common-word"
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = _gloss(names=["Law"], arc_titles={"Dressrosa": ["Trafalgar D. Water Law"]})
    assert "Trafalgar D. Water Law" in gv.apply_results(g, {"Law": high("Trafalgar D. Water Law")})["phrases"]
