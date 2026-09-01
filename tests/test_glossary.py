"""Unit tests for glossary.py (C1). Pure functions; wordlist from the bundled fallback."""

import glossary


def gloss(names=None, phrases=None, hard_fixes=None, prompt="", show="Test"):
    return glossary.load_dict(
        {
            "show": show,
            "names": names or [],
            "phrases": phrases or [],
            "hard_fixes": hard_fixes or {},
            "initial_prompt": prompt,
        }
    )


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
    g = glossary.load_dict(
        {
            "show": "One Pace",
            "names": ["Luffy"],
            "phrases": ["Enies Lobby"],
            "hard_fixes": {"Spondum": "Spandam", "Eddie's Lobby": "Enies Lobby"},
            "initial_prompt": "p",
        }
    )
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


def test_name_suspect_flags_lowercase_near_name_misspelling(monkeypatch):
    """Pin the word set: this assertion's result depends on whether the OS wordlist is
    installed. It passed locally only because /usr/share/dict/american-english is absent
    here and present (104k words) in the container -- so it was testing the dev box, not
    the behaviour."""
    monkeypatch.setattr(glossary, "_WORDS", {"we", "beat", "today", "the", "saw"})
    assert glossary.name_suspect("we beat zorro today", gloss(names=["Zoro"]))


def test_name_suspect_does_not_flag_a_misspelling_that_is_a_real_english_word(monkeypatch):
    """The C1 English-word gate, doing its job -- and the real production behaviour for
    this exact pair: `zorro` IS in the container's dictionary, so a Whisper mishear of
    Zoro as Zorro is deliberately NOT corrected. Recorded so the gate's cost is visible
    rather than discovered."""
    monkeypatch.setattr(glossary, "_WORDS", {"we", "beat", "today", "zorro"})
    assert not glossary.name_suspect("we beat zorro today", gloss(names=["Zoro"]))


def test_name_suspect_ignores_clean_line_of_english_and_known_names():
    assert not glossary.name_suspect("Luffy hit the pirates", gloss(names=["Luffy"]))


def test_name_suspect_ignores_sentence_initial_english_word():
    # a capitalized word that IS a known English word must not be flagged as a name
    assert not glossary.name_suspect("Maybe the people come", gloss(names=["Luffy"]))


# --- T5: tier-4 phonetic match (V2 A4) ---------------------------------------


def test_phonetic_matches_spondum():
    # "spondum"/"Spandam" both Metaphone to "SPNTM", but the letters diverge enough
    # (SequenceMatcher ratio ~0.71) to fail the guarded-fuzzy cutoff (0.90 at len 7) --
    # exactly the far-mishear case tier 4 exists to recover.
    g = gloss(names=["Spandam"])
    assert glossary.correct("it was Spondum today", g)[0] == "it was Spandam today"


def test_phonetic_does_not_match_english_word():
    # "frank" Metaphones identically to "Franky" (FRNK) but is a real English word --
    # the is_english() gate (checked before any correction tier fires) must still block
    # it, same as it already does for the fuzzy tier.
    g = gloss(names=["Franky"])
    assert glossary.correct("frank told him so", g) == ("frank told him so", 0)


def test_phonetic_graceful_if_jellyfish_missing(monkeypatch):
    monkeypatch.setattr(glossary, "jellyfish", None)
    assert glossary._phonetic_match("spondum", ["Spandam"]) is None
    g = gloss(names=["Spandam"])
    # No hard_fix and the fuzzy cutoff rejects it (see test_phonetic_matches_spondum) --
    # without jellyfish this must degrade to a no-op, not raise.
    assert glossary.correct("it was Spondum today", g) == ("it was Spondum today", 0)


def test_hard_fix_never_fires_inside_a_longer_token():
    """glossary_acquire writes short variants as hard_fixes; token-level substitution is
    what keeps 'Hoshi' from rewriting the middle of 'Shirahoshi'."""
    g = glossary.load_dict({"names": [], "hard_fixes": {"hoshi": "Hoshi"}})
    out, n = glossary.correct("Shirahoshi met Hoshi", g)
    assert out == "Shirahoshi met Hoshi"
    assert "ShiraHoshi" not in out


# --- prompt derivation and tier classification (spec v5, S-3) -----------------


def test_prompt_for_prefers_the_glossarys_own_prompt():
    g = glossary.load_dict({"show": "One Pace", "initial_prompt": "Luffy, Zoro, Nami"})
    assert glossary.prompt_for(g) == "Luffy, Zoro, Nami"


def test_prompt_for_falls_back_to_a_show_neutral_prompt():
    g = glossary.load_dict({"show": "One Pace"})
    p = glossary.prompt_for(g)
    assert "One Pace" in p and "English dub" in p


def test_prompt_for_falls_back_again_with_no_show_at_all():
    p = glossary.prompt_for(glossary.load_dict({}))
    assert "Japanese anime" in p and "One Pace" not in p


def test_an_explicit_show_overrides_the_glossarys_own():
    """generate.load_glossary() prefers SHOW_NAME over the glossary's `show` key; the
    derivation used for comparison has to agree with it or every episode of a show with
    both set would read as prompt-changed forever."""
    g = glossary.load_dict({"show": "Wrong Show"})
    assert "Right Show" in glossary.prompt_for(g, show="Right Show")


def test_a_hard_fixes_only_edit_does_not_change_the_prompt():
    """mine_glossary.py appends hard_fixes on EVERY sweep of a watched show. Those never
    reach initial_prompt, so they must not mark anything transcription-stale -- hashing
    the glossary FILE would flag every episode of the show and re-queue it for the GPU."""
    before = glossary.load_dict({"show": "One Pace", "hard_fixes": {"hockey": "Haki"}})
    after = glossary.load_dict({"show": "One Pace", "hard_fixes": {"hockey": "Haki", "buster": "Buster"}})
    assert glossary.prompt_for(before) == glossary.prompt_for(after)
    assert glossary.stale_tier(glossary.prompt_for(before), after) is None


def test_a_prompt_changing_edit_is_transcription_stale():
    before = glossary.load_dict({"show": "One Pace", "initial_prompt": "Luffy, Zoro"})
    after = glossary.load_dict({"show": "One Pace", "initial_prompt": "Luffy, Zoro, Nami"})
    assert glossary.stale_tier(glossary.prompt_for(before), after) == "transcribe"


def test_an_unknown_stored_prompt_is_transcription_stale():
    """No stored prompt means no evidence the transcript matches the current glossary.
    Unknown provenance is not evidence of freshness."""
    g = glossary.load_dict({"show": "One Pace"})
    assert glossary.stale_tier(None, g) == "transcribe"
    assert glossary.stale_tier("", g) == "transcribe"


def test_a_names_only_edit_does_not_change_the_prompt_either():
    """`names` drives correct(), not the decoder -- only initial_prompt reaches whisper."""
    before = glossary.load_dict({"show": "One Pace", "names": ["Luffy"]})
    after = glossary.load_dict({"show": "One Pace", "names": ["Luffy", "Zoro"]})
    assert glossary.stale_tier(glossary.prompt_for(before), after) is None


def test_arc_for_reads_the_season_nfo_title(tmp_path):
    """[S-1] The arc name comes from season.nfo, which Plex/Jellyfin/Sonarr already write.
    Verified on the live library: One Pace/Season 31/season.nfo says <title>Dressrosa</title>."""
    d = tmp_path / "One Pace" / "Season 31"
    d.mkdir(parents=True)
    (d / "season.nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<season>\n  <seasonnumber>31</seasonnumber>\n'
        "  <title>Dressrosa</title>\n</season>\n"
    )
    assert glossary.arc_for(str(d / "One Pace - S31E01 - Whatever.mkv")) == "Dressrosa"


def test_arc_for_returns_none_without_a_season_nfo(tmp_path):
    """Most of the library has no season.nfo. That is a normal state, not an error: the
    caller falls back to unweighted terms rather than failing the episode."""
    d = tmp_path / "Some Show" / "Season 01"
    d.mkdir(parents=True)
    assert glossary.arc_for(str(d / "ep.mkv")) is None


def test_arc_for_survives_a_malformed_season_nfo(tmp_path):
    """A truncated or non-XML season.nfo must not raise -- a metadata file this pipeline
    does not own must never be able to fail a transcription."""
    d = tmp_path / "Some Show" / "Season 02"
    d.mkdir(parents=True)
    (d / "season.nfo").write_text("<season><title>Unclosed")
    assert glossary.arc_for(str(d / "ep.mkv")) is None


def test_source_episodes_parses_a_range(tmp_path):
    p = tmp_path / "ep.nfo"
    p.write_text("<plot>Dressrosa!\n\nCovers anime episode(s): 628 - 631\n</plot>")
    assert glossary.source_episodes(str(p)) == [628, 629, 630, 631]


def test_source_episodes_parses_comma_and_single_and_mixed_forms(tmp_path):
    p1 = tmp_path / "a.nfo"
    p1.write_text("Covers anime episode(s): 628, 630, 645")
    assert glossary.source_episodes(str(p1)) == [628, 630, 645]
    p2 = tmp_path / "b.nfo"
    p2.write_text("Covers anime episode(s): 628")
    assert glossary.source_episodes(str(p2)) == [628]
    p3 = tmp_path / "c.nfo"
    p3.write_text("Covers anime episode(s): 628-630, 645")
    assert glossary.source_episodes(str(p3)) == [628, 629, 630, 645]


def test_source_episodes_absent_line_and_missing_file(tmp_path):
    p = tmp_path / "d.nfo"
    p.write_text("<plot>No mapping here.</plot>")
    assert glossary.source_episodes(str(p)) == []
    assert glossary.source_episodes(str(tmp_path / "missing.nfo")) == []


def test_source_episodes_survives_a_truncated_file(tmp_path):
    p = tmp_path / "e.nfo"
    p.write_bytes(b"Covers anime episode(s): 6")  # cut mid-number, still parses as [6]
    assert glossary.source_episodes(str(p)) == [6]


def test_tag_names_by_arc_marks_only_names_the_arc_actually_contains():
    """[S-11] Tags come from wiki arc membership, so a name the arc does not contain is
    left untagged rather than tagged falsely -- untagged defaults IN at the consumer, and a
    wrong tag would actively demote a name in the arcs it belongs to."""
    g = glossary.load_dict({"names": ["Doflamingo", "Spandam", "Luffy"], "hard_fixes": {}})
    n = glossary.tag_names_by_arc(g, "Dressrosa", {"Donquixote Doflamingo", "Rebecca", "Monkey D. Luffy"})
    assert g["arc_tags"]["doflamingo"] == ["Dressrosa"]
    assert g["arc_tags"]["luffy"] == ["Dressrosa"]
    assert "spandam" not in g["arc_tags"]
    assert n == 2


def test_tag_names_by_arc_accumulates_arcs_for_a_recurring_character():
    """A character in two arcs must be tagged with BOTH. Caesar Clown is a Punk Hazard
    antagonist present in Dressrosa; a single-valued tag would exclude him from one of
    them, which is the contradiction the round-1 review caught."""
    g = glossary.load_dict({"names": ["Caesar"], "hard_fixes": {}})
    glossary.tag_names_by_arc(g, "Punk Hazard", {"Caesar Clown"})
    glossary.tag_names_by_arc(g, "Dressrosa", {"Caesar Clown"})
    assert g["arc_tags"]["caesar"] == ["Dressrosa", "Punk Hazard"]


def test_tag_names_by_arc_is_idempotent():
    """Re-running a sweep must not duplicate tags."""
    g = glossary.load_dict({"names": ["Doflamingo"], "hard_fixes": {}})
    for _ in range(3):
        glossary.tag_names_by_arc(g, "Dressrosa", {"Donquixote Doflamingo"})
    assert g["arc_tags"]["doflamingo"] == ["Dressrosa"]


def test_tag_names_by_arc_ignores_an_empty_title_set():
    """[S-7]: an arc that would not resolve yields no titles, and must therefore change
    nothing rather than clearing existing tags."""
    g = glossary.load_dict({"names": ["Doflamingo"], "hard_fixes": {}})
    glossary.tag_names_by_arc(g, "Dressrosa", {"Donquixote Doflamingo"})
    glossary.tag_names_by_arc(g, "Gaimon", set())
    assert g["arc_tags"]["doflamingo"] == ["Dressrosa"]
