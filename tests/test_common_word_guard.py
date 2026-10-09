"""The common-word guard for glossary VERIFY auto-writes (VERIFY_SKIP_COMMON_WORDS=1).

A single-token English word expanded into a longer wiki title is flagged 'common-word' for
review, not silently written.  Opt-in (default off: byte-identical behaviour).  The arc gate
overrides: an English word that IS in the arc universe is written, not flagged."""

import json

import pytest

import glossary
import glossary_verify as gv

# The host's word list decides what the guard calls an ordinary word (the bundled list is 233 words here, production's image has
# wamerican with ~100k, which spells proper names CAPITALISED: Hancock, Rayleigh; ordinary words lowercase: castle, lobby), so no
# test may depend on it: every test runs against exactly these entries, spelled as a word list spells them.
ENTRIES = ["government", "castle", "lobby", "elders", "jolly", "world", "Hancock", "Rayleigh"]


@pytest.fixture(autouse=True)
def english_words(monkeypatch):
    monkeypatch.setattr(glossary, "_WORDS", {w.lower() for w in ENTRIES})  # the fuzzy path's lowercased set, untouched
    monkeypatch.setattr(glossary, "_ORDINARY", {w for w in ENTRIES if w == w.lower()})


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


def test_arc_gate_overrides_common_word_guard_only_with_its_own_flag(monkeypatch):
    """An English word whose canonical IS in the arc universe is written -- but only when VERIFY_COMMON_WORD_ARC_RESCUE=1:
    measured, the rescue lets back 58 of the 99 wrong writes the guard blocks (generic words are on arc pages)."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setenv("VERIFY_COMMON_WORD_ARC_RESCUE", "1")
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
    monkeypatch.setattr(glossary, "_ORDINARY", None)  # reload from the bundled list plus this file
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(words))
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["CASTLE", "Government"])
    new = gv.apply_results(g, {"CASTLE": high("Drum Castle"), "Government": high("World Government")})
    assert new["flagged"] == {"CASTLE": {"reason": "common-word", "canonical": "Drum Castle"}}
    assert "World Government" in new["phrases"]  # not in this list, so not a common word here


def test_a_name_that_is_also_an_english_word_is_flagged_for_review_not_dropped(monkeypatch):
    """The documented cost: a big dictionary holds words that are names in the show (Law, Smoker). The guard flags them for
    review; it never deletes the term or the canonical, and the arc rescue (its own flag) can let them through."""
    monkeypatch.setattr(glossary, "_ORDINARY", {w for w in ENTRIES if w == w.lower()} | {"law"})
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=["Law"])
    new = gv.apply_results(g, {"Law": high("Trafalgar D. Water Law")})
    assert new["names"] == ["Law"] and new["flagged"]["Law"]["reason"] == "common-word"
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setenv("VERIFY_COMMON_WORD_ARC_RESCUE", "1")
    g = _gloss(names=["Law"], arc_titles={"Dressrosa": ["Trafalgar D. Water Law"]})
    assert "Trafalgar D. Water Law" in gv.apply_results(g, {"Law": high("Trafalgar D. Water Law")})["phrases"]


def test_without_the_rescue_flag_the_arc_gate_does_not_override(monkeypatch):
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.delenv("VERIFY_COMMON_WORD_ARC_RESCUE", raising=False)
    g = _gloss(names=["Castle"], arc_titles={"Drum Island": ["Drum Castle"]})
    new = gv.apply_results(g, {"Castle": high("Drum Castle")})
    assert new["flagged"]["Castle"] == {"reason": "common-word", "canonical": "Drum Castle"}


# ---- only a word the list spells in LOWERCASE is an ordinary word ------------------------------------------------


@pytest.mark.parametrize("term", ["Hancock", "Rayleigh", "hancock", "HANCOCK"])
def test_a_name_the_list_spells_capitalised_is_not_a_common_word(monkeypatch, term):
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    g = _gloss(names=[term])
    new = gv.apply_results(g, {term: high(f"Boa {term}")})
    assert f"Boa {term}" in new["phrases"] and "flagged" not in new


@pytest.mark.parametrize("term", ["castle", "Castle", "CASTLE"])
def test_a_word_the_list_spells_lowercase_is_a_common_word_whatever_the_terms_case(monkeypatch, term):
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    new = gv.apply_results(_gloss(names=[term]), {term: high("Drum Castle")})
    assert new["flagged"][term]["reason"] == "common-word"


def test_the_ordinary_word_set_keeps_the_lists_case_and_the_fuzzy_path_is_untouched(monkeypatch, tmp_path):
    words = tmp_path / "words"
    words.write_text("castle\nHancock\nlobby\nit's\nSmoker\nsmoker\n")
    monkeypatch.setattr(glossary, "_WORDS", None)
    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(words))
    assert glossary.is_ordinary_word("Castle") and glossary.is_ordinary_word("lobby")
    assert not glossary.is_ordinary_word("Hancock")  # listed only capitalised: a name
    assert glossary.is_ordinary_word("smoker")  # listed both ways: the lowercase entry makes it a word
    assert not glossary.is_ordinary_word("it's")  # entries with an apostrophe are dropped, as for is_english
    assert glossary.is_english("Hancock")  # is_english still lowercases everything: the fuzzy path is unchanged


# ---- review fixes: the rescue needs the universe, a missing word list is loud ------------------------------


def test_the_rescue_needs_the_canonical_to_be_in_the_universe(monkeypatch):
    """Mutation guard: rescue flag + gate on, canonical NOT on an arc page: the English word stays flagged."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setenv("VERIFY_COMMON_WORD_ARC_RESCUE", "1")
    g = _gloss(names=["Government"], arc_titles={"Drum Island": ["Drum Castle"]})
    new = gv.apply_results(g, {"Government": high("World Government")})
    assert new["flagged"]["Government"]["reason"] == "common-word"


def test_the_rescue_does_nothing_without_the_arc_gate(monkeypatch):
    """The rescue reads the arc universe, which exists only with VERIFY_ARC_GATE=1."""
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    monkeypatch.setenv("VERIFY_COMMON_WORD_ARC_RESCUE", "1")
    monkeypatch.delenv("VERIFY_ARC_GATE", raising=False)
    g = _gloss(names=["Castle"], arc_titles={"Drum Island": ["Drum Castle"]})
    assert gv.apply_results(g, {"Castle": high("Drum Castle")})["flagged"]["Castle"]["reason"] == "common-word"


def test_a_missing_word_list_is_logged_once_and_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", None)
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(tmp_path / "nonexistent"))
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    glossary.ordinary_words()
    glossary.is_ordinary_word("castle")
    shown = capsys.readouterr().out
    assert shown.count("word list") == 1 and "unreadable" in shown and "bundled" in shown
    assert glossary.wordlist_status() == "missing"


def test_the_verify_report_says_the_word_list_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", None)
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(tmp_path / "nonexistent"))
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    rep = _verify_report(monkeypatch, tmp_path)
    assert rep["common_word"]["wordlist"] == "missing"


def test_a_readable_word_list_adds_no_wordlist_key(monkeypatch, tmp_path):
    """GUARD: the report block only gains the key when something is wrong."""
    words = tmp_path / "words"
    words.write_text("government\n")
    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", None)
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(words))
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "1")
    assert _verify_report(monkeypatch, tmp_path)["common_word"] == {"blocked": 1}


def _verify_report(monkeypatch, tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(_gloss(names=["Government", "Momonosuke"])))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["World Government", "Kouzuki Momonosuke"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    results = {"Government": high("World Government"), "Momonosuke": high("Kouzuki Momonosuke")}
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: results[term])
    return gv.verify(str(path))
