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


# --- T3: correct() tiered ----------------------------------------------------

def test_correct_does_not_touch_real_english_words():
    g = gloss(names=["Arlong", "Franky", "Spandam", "Alabasta"])
    for line in ["those pirates ran", "frank work along the line", "seven of them fall"]:
        assert glossary.correct(line, g) == (line, 0)


def test_correct_applies_exact_token_hard_fix_case_insensitive_keeps_punct():
    g = gloss(hard_fixes={"spondum": "Spandam"})
    assert glossary.correct("then Spondum, the chief", g)[0] == "then Spandam, the chief"


def test_correct_applies_phrase_hard_fix():
    g = gloss(hard_fixes={"eddie's lobby": "Enies Lobby"})
    assert glossary.correct("we reach Eddie's Lobby soon", g)[0] == "we reach Enies Lobby soon"


def test_correct_guarded_fuzzy_fires_on_non_english_substitution_misspelling():
    g = gloss(names=["Alabasta"])
    assert glossary.correct("bound for Arabasta", g)[0] == "bound for Alabasta"


def test_correct_guarded_fuzzy_refuses_one_char_indel():
    g = gloss(names=["Spandam"])
    assert glossary.correct("it was Spandm", g) == ("it was Spandm", 0)  # left for the LLM


def test_correct_phrase_runs_before_token_and_noop_without_glossary():
    g = gloss(phrases=["Water Seven"], hard_fixes={"water seven": "Water Seven"})
    assert glossary.correct("from water seven port", g)[0] == "from Water Seven port"
    assert glossary.correct("anything at all", gloss()) == ("anything at all", 0)


# --- T4: name_suspect --------------------------------------------------------

def test_name_suspect_flags_unknown_capitalized_proper_noun():
    assert glossary.name_suspect("I saw Krieg coming", gloss(names=["Luffy"]))


def test_name_suspect_flags_lowercase_near_name_misspelling():
    assert glossary.name_suspect("we beat zorro today", gloss(names=["Zoro"]))


def test_name_suspect_ignores_clean_line_of_english_and_known_names():
    assert not glossary.name_suspect("Luffy hit the pirates", gloss(names=["Luffy"]))


def test_name_suspect_ignores_sentence_initial_english_word():
    # a capitalized word that IS a known English word must not be flagged as a name
    assert not glossary.name_suspect("Maybe the people come", gloss(names=["Luffy"]))
