"""Unit tests for glossary.py (C1). Pure functions; wordlist from the bundled fallback."""
import glossary


def gloss(names=None, phrases=None, hard_fixes=None, prompt="", show="Test"):
    return glossary.load_dict({
        "show": show, "names": names or [], "phrases": phrases or [],
        "hard_fixes": hard_fixes or {}, "initial_prompt": prompt,
    })


# --- T1: scaffold / contracts ------------------------------------------------

def test_module_constants_present():
    assert glossary.MIN_FUZZY_LEN == 4
    assert glossary.fuzzy_cutoff(4) == 0.95
    assert glossary.fuzzy_cutoff(12) < glossary.fuzzy_cutoff(4)


# --- T2: is_english gate + load_dict -----------------------------------------

def test_is_english_recognizes_common_words_case_insensitively():
    assert glossary.is_english("work")
    assert glossary.is_english("Work")
    assert glossary.is_english("along")
    assert glossary.is_english("pirates")


def test_is_english_rejects_proper_nouns_and_mishears():
    assert not glossary.is_english("spondum")
    assert not glossary.is_english("Spandam")
    assert not glossary.is_english("Luffy")


def test_load_dict_splits_phrase_and_token_fixes():
    g = glossary.load_dict({
        "show": "One Pace", "names": ["Luffy"], "phrases": ["Enies Lobby"],
        "hard_fixes": {"Spondum": "Spandam", "Eddie's Lobby": "Enies Lobby"},
        "initial_prompt": "p",
    })
    assert g["token_fixes"] == {"spondum": "Spandam"}
    assert g["phrase_fixes"] == {"eddie's lobby": "Enies Lobby"}
    assert g["names"] == ["Luffy"]
    assert g["phrases"] == ["Enies Lobby"]
    assert g["initial_prompt"] == "p"


def test_load_blank_path_is_noop_glossary():
    g = glossary.load("")
    assert g["names"] == [] and g["token_fixes"] == {} and g["phrase_fixes"] == {}
