"""The decision store: a human's verdict on a repaired line, made durable.

`accept_repair` states the acceptance bar and its own docstring says nothing below it
enforces that. The enforcement is a person reading the lines, and until this module the
verdicts lived only as prose in `docs/Adversarial Reviews/`. These tests cover the store
that makes them software.
"""

import decisions


def test_key_normalises_case_and_whitespace_but_keeps_punctuation():
    """Breaks if key() stops folding case or runs of whitespace, or STARTS folding
    punctuation away.

    Punctuation-only repairs are the majority of this stage's work, so punctuation is
    part of the identity of a line: `CP-0.` and `CP?` are a real ASR/proposal pair from
    the 2026-08-27 review, and a verdict rejecting one must never match the other."""
    assert decisions.key("  We're  Looking  For A Factory. ") == decisions.key("we're looking for a factory.")
    assert decisions.key("CP-0.") != decisions.key("CP?")


def test_lookup_matches_the_pair_and_only_the_pair():
    """Breaks if lookup() stops keying on BOTH sides of the pair.

    Keying on `orig` alone would be the dangerous simplification: the owner rejected
    `It's a VIVRA card?` -> `It's a Vivi card?` because Vivi is a character and a Vivre
    Card is an object. That rejection must not also suppress a DIFFERENT proposal for the
    same line -- a later model offering `Vivre card` is the fix, not the regression."""
    store = decisions.record({}, "It's a VIVRA card?", "It's a Vivi card?", "reject", note="wrong referent")
    hit = decisions.lookup(store, "It's a VIVRA card?", "It's a Vivi card?")
    assert hit is not None
    assert hit["verdict"] == "reject"
    assert decisions.lookup(store, "It's a VIVRA card?", "It's a Vivre card?") is None


def test_record_refuses_an_empty_side_of_the_pair():
    """Breaks if record() stops guarding empty keys. An empty `orig` or `proposed`
    normalises to "" and would then match far too broadly -- every card the LLM returned
    nothing for shares that key."""
    assert decisions.record({}, "", "It's a Vivi card?", "reject").get("decisions", []) == []
    assert decisions.record({}, "It's a VIVRA card?", "", "reject").get("decisions", []) == []
    # whitespace-only too: the guard must test the NORMALISED key, not the raw argument.
    assert decisions.record({}, "   ", "It's a Vivi card?", "reject").get("decisions", []) == []
    assert decisions.record({}, "It's a VIVRA card?", "\t\n ", "reject").get("decisions", []) == []


def test_a_correct_that_restores_the_original_is_stored_as_a_reject():
    """Breaks if record() stops normalising a no-op `correct`.

    `Spare Mata-koth for me!` -> `Sparing Mata-koth for me!` was rejected on 2026-08-27.
    A reviewer can reach that same outcome by choosing `correct` and typing the original
    back, and that is semantically a rejection. Stored as `correct`, lookup would have two
    spellings of one outcome and the [S-4] consult would need to handle both."""
    store = decisions.record(
        {}, "Spare Mata-koth for me!", "Sparing Mata-koth for me!", "correct", text="Spare Mata-koth for me!"
    )
    assert store["decisions"][0]["verdict"] == "reject"
    # ...and the correction text goes with it. A reject still carrying `text` is the same
    # two-spellings-of-one-outcome the conversion exists to prevent.
    assert "text" not in store["decisions"][0]


def test_save_creates_the_shows_file_then_appends_without_losing_the_first(tmp_path):
    """Breaks if save() stops creating a missing file, or if a second verdict overwrites
    rather than joins the first.

    A show's store has to appear on first use the way mine_glossary.py creates a glossary
    from nothing -- nobody hand-creates one -- and losing an earlier verdict would silently
    re-open a call the owner already made."""
    store = decisions.record({}, "It's a VIVRA card?", "It's a Vivi card?", "reject")
    assert decisions.save(store, "One Pace", dir=str(tmp_path)) is True
    assert (tmp_path / "One Pace.json").exists()

    again = decisions.load("One Pace", dir=str(tmp_path))
    decisions.record(again, "That come together.", "That comes together.", "accept")
    assert decisions.save(again, "One Pace", dir=str(tmp_path)) is True

    final = decisions.load("One Pace", dir=str(tmp_path))
    assert [d["verdict"] for d in final["decisions"]] == ["reject", "accept"]
    assert final["show"] == "One Pace"


def test_a_corrupt_store_loads_empty_rather_than_half_loaded(tmp_path):
    """Breaks if load() starts returning a partial parse. A store read as SMALLER than it
    is looks exactly like a store with fewer verdicts, so every missing decision silently
    falls through to accept_repair. Refuse the whole file instead."""
    (tmp_path / "One Pace.json").write_text('{"decisions": [{"orig": "a"')
    assert decisions.load("One Pace", dir=str(tmp_path)) == {}
    assert decisions.load("Nothing Here", dir=str(tmp_path)) == {}


def test_a_failed_save_leaves_the_previous_file_intact_and_no_debris(tmp_path, monkeypatch):
    """Breaks if save() ever writes the real path directly instead of temp-then-replace.

    Writing in place would truncate a good store the moment a write fails partway, losing
    every verdict already in it to save one that was never completed. The reader here is
    repair.py, mid-episode."""
    store = decisions.record({}, "It's a VIVRA card?", "It's a Vivi card?", "reject")
    assert decisions.save(store, "One Pace", dir=str(tmp_path)) is True
    before = (tmp_path / "One Pace.json").read_text()

    decisions.record(store, "That come together.", "That comes together.", "accept")

    def die(*a, **kw):
        raise OSError("no space left on device")

    monkeypatch.setattr(decisions.json, "dump", die)
    assert decisions.save(store, "One Pace", dir=str(tmp_path)) is False
    assert (tmp_path / "One Pace.json").read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["One Pace.json"], "a failed save left a temp file behind"


def _library(tmp_path, show_dirname):
    """A minimal library: a glossary dir, a decisions dir, and an episode nested two deep."""
    gloss_dir, dec_dir = tmp_path / "glossaries", tmp_path / "decisions"
    gloss_dir.mkdir(exist_ok=True)
    dec_dir.mkdir(exist_ok=True)
    ep = tmp_path / "media" / show_dirname / "Season 31" / "E01.mkv"
    ep.parent.mkdir(parents=True)
    return gloss_dir, dec_dir, ep


def test_decisions_for_resolves_the_store_by_the_same_walk_glossary_for_uses(tmp_path):
    """Breaks if decisions_for() stops walking up to the show directory. An episode lives
    two levels below the show, so resolving on its own directory finds nothing."""
    gloss_dir, dec_dir, ep = _library(tmp_path, "One Pace")
    (gloss_dir / "One Pace.json").write_text('{"show": "One Pace"}')
    decisions.save(decisions.record({}, "It's a VIVRA card?", "It's a Vivi card?", "reject"), "One Pace", dir=str(dec_dir))

    store, show = decisions.decisions_for(str(ep), gloss_dir=str(gloss_dir), dir=str(dec_dir))
    assert show == "One Pace"
    assert len(store["decisions"]) == 1


def test_the_store_is_named_for_the_show_directory_not_the_glossarys_display_name(tmp_path):
    """Breaks if show identity is taken from the glossary's `show` KEY instead of the
    directory the glossary file is named for.

    `glossaries/Cowboy Bebop (1998) {tvdb-76885}.json` carries `show == "Cowboy Bebop"`.
    Keyed on that, the decision store would be `Cowboy Bebop.json` while the glossary is
    `Cowboy Bebop (1998) {tvdb-76885}.json` -- two artifacts for one show that never agree,
    and a store that silently misses every lookup."""
    dirname = "Cowboy Bebop (1998) {tvdb-76885}"
    gloss_dir, dec_dir, ep = _library(tmp_path, dirname)
    (gloss_dir / (dirname + ".json")).write_text('{"show": "Cowboy Bebop"}')

    _, show = decisions.decisions_for(str(ep), gloss_dir=str(gloss_dir), dir=str(dec_dir))
    assert show == dirname


def test_a_missing_decisions_dir_yields_an_empty_store_not_an_error(tmp_path):
    """Breaks if an absent DECISIONS_DIR raises. Having no decisions is the pre-existing
    state of every install, so it must cost nothing -- the caller falls through to
    accept_repair, which is today's behaviour."""
    gloss_dir, _, ep = _library(tmp_path, "One Pace")
    (gloss_dir / "One Pace.json").write_text('{"show": "One Pace"}')

    store, show = decisions.decisions_for(str(ep), gloss_dir=str(gloss_dir), dir=str(tmp_path / "absent"))
    assert store == {}
    assert show == "One Pace"


def test_promote_writes_a_hard_fix_without_touching_the_caller_s_glossary():
    """Breaks if promote() mutates its argument instead of deep-copying.

    Every write path in glossary_acquire.py deep-copies first -- apply_proposals:672,
    record_decision:783, revert:727 -- and says why: "so curated hard_fixes, names and
    initial_prompt survive untouched." A promotion that mutates in place would edit a
    glossary another caller is still holding."""
    gloss = {"hard_fixes": {}}
    out, applied = decisions.promote(gloss, {"hard_fix": {"Samadai": "Samurai"}})
    assert out["hard_fixes"]["Samadai"] == "Samurai"
    assert applied == {"Samadai": "Samurai"}
    assert gloss["hard_fixes"] == {}, "promote() mutated the caller's glossary"


def test_a_promotion_is_marked_as_a_humans_decision():
    """Breaks if promote() stops stamping run == "review".

    That marker is this repo's trust anchor for human curation: glossary_acquire.revert
    refuses to delete an entry carrying it (R4, glossary_acquire.py:730). Without it, an
    automated --revert sweep could quietly undo a call the owner made by hand."""
    out, _ = decisions.promote({}, {"hard_fix": {"Samadai": "Samurai"}})
    assert out["acquired"]["Samadai"]["run"] == "review"
    assert out["acquired"]["Samadai"]["canonical"] == "Samurai"


def test_promote_never_overwrites_an_entry_already_in_the_glossary():
    """Breaks if promote() clobbers a curated fix. A human's glossary outranks a
    promotion: the glossary is hand-maintained and committed, the promotion is one
    reviewer's call on one line."""
    gloss = {"hard_fixes": {"Samadai": "Samurai Warrior"}}
    out, applied = decisions.promote(gloss, {"hard_fix": {"Samadai": "Samurai"}})
    assert out["hard_fixes"]["Samadai"] == "Samurai Warrior"
    assert applied == {}, "a refused promotion must report that it applied nothing"


def test_the_existing_entry_check_is_case_insensitive():
    """Breaks if promote() compares keys case-sensitively.

    glossary.load_dict lowercases every hard_fixes key at load (glossary.py:70-72), so
    `samadai` and `Samadai` are ONE fix downstream. Comparing with case would let a
    promotion write a second key that silently shadows or contradicts the curated one."""
    gloss = {"hard_fixes": {"samadai": "Samurai Warrior"}}
    out, applied = decisions.promote(gloss, {"hard_fix": {"Samadai": "Samurai"}})
    assert applied == {}
    assert out["hard_fixes"] == {"samadai": "Samurai Warrior"}


def test_a_decision_records_what_actually_promoted_not_what_was_asked():
    """Breaks if record() stops carrying `promoted` through, or starts recording a
    promotion that was refused.

    The audit trail has to say what LANDED. A decision claiming it promoted `Samadai`
    when the curated glossary refused the write would send the next reader looking for a
    hard_fix that is not there."""
    gloss = {"hard_fixes": {"Samadai": "Samurai Warrior"}}
    _, refused = decisions.promote(gloss, {"hard_fix": {"Samadai": "Samurai"}})
    args = ("my fellow Samadai,", "my fellow Samadai.", "correct")
    store = decisions.record({}, *args, text="my fellow Samurai.", promoted=refused)
    assert "promoted" not in store["decisions"][0]

    _, applied = decisions.promote({}, {"hard_fix": {"Samadai": "Samurai"}})
    store = decisions.record({}, *args, text="my fellow Samurai.", promoted=applied)
    assert store["decisions"][0]["promoted"] == {"Samadai": "Samurai"}


def test_a_second_verdict_for_the_same_pair_replaces_the_first():
    """Breaks if record() appends a duplicate pair instead of replacing it.

    A review store whose whole purpose is a human's answer must let that human change it.
    Appending leaves lookup() returning the OLDEST verdict, so a correction is written to
    the file, shipped to git, and permanently unreachable.

    This is the both-states bug `glossary_acquire.apply_proposals` documents as I3/C2
    (glossary_acquire.py:668): "every verdict clears whatever a PRIOR run -- automated or
    human -- left behind for the same term ... exactly the both-states bug this module
    exists to avoid reintroducing." """
    store = decisions.record({}, "We're looking for a factory.", "We're looking for a needle.", "reject")
    store = decisions.record(store, "We're looking for a factory.", "We're looking for a needle.", "accept")
    assert len(store["decisions"]) == 1
    hit = decisions.lookup(store, "We're looking for a factory.", "We're looking for a needle.")
    assert hit is not None and hit["verdict"] == "accept"


def test_record_refuses_a_verdict_outside_the_defined_set():
    """Breaks if record() stops validating the verdict.

    A typo'd verdict is stored verbatim and then matches nothing the [S-4] consult
    branches on, so the line falls through to accept_repair as though never reviewed --
    while the store claims it was."""
    # Deliberately untyped: a verdict reaches record() from a JSON request body, so it can
    # be any type at all, and refusing None is exactly what this guard is for.
    malformed: list = ["aceptt", "", None, "REJECT", 0, ["reject"]]
    for bad in malformed:
        assert decisions.record({}, "orig line", "prop line", bad).get("decisions", []) == []


def test_a_correct_without_usable_text_is_refused():
    """Breaks if record() accepts a `correct` carrying no replacement text.

    The consult does `new = d["text"]` for a correct verdict. A missing key raises
    mid-episode, which violates this project's never-fail-an-episode contract, and a
    whitespace-only text renders a blank card -- worse than the repair it replaced."""
    assert decisions.record({}, "orig line", "prop line", "correct").get("decisions", []) == []
    assert decisions.record({}, "orig line", "prop line", "correct", text="   ").get("decisions", []) == []


def test_key_folds_the_curly_apostrophe_onto_the_straight_one():
    """Breaks if key() stops treating the two apostrophe glyphs as one character.

    Whisper and the repair LLM both vary in which glyph they emit, and English dub
    dialogue is full of contractions -- so this is not an edge case, it is most lines.
    Unlike `CP-0.` vs `CP?`, the two apostrophes are a rendering artifact and not a
    semantic distinction.

    `glossary_acquire.reduce_form` already folds both (_REDUCE_RE, glossary_acquire.py:33)
    and warns why the character must be written as chr(0x2019): a literal curly apostrophe
    "gets silently normalised to U+0027 by editors in this toolchain, which silently
    disables curly-apostrophe stripping and passes a literal-looking review." Same trap
    here, same defence."""
    curly = "It" + chr(0x2019) + "s a VIVRA card?"
    straight = "It" + chr(0x27) + "s a VIVRA card?"
    assert decisions.key(curly) == decisions.key(straight)
    assert decisions.key("CP-0.") != decisions.key("CP?"), "folding must not reach real punctuation"


def test_record_stamps_a_verdict_with_the_time_it_was_made(monkeypatch):
    """A verdict recorded AFTER an episode's last mux never reaches the video: mux.py
    treats the stamp as its only skip guard, and nothing re-opens the episode. Measured on
    One Pace, 2026-08-29: 11 of 20 human corrections were still absent from the shipped
    track, every affected stamp predating the store.

    A sweep can only be idempotent if it can tell a verdict that is newer than the stamp
    from one already shipped -- otherwise it re-opens every eligible episode on every pass
    forever. Entries carried no time at all, so this is the missing primitive. Stored as an
    epoch float, the same unit `common.write_stamp` records `mtime` in, so the comparison
    is a subtraction rather than a parse.

    The break this catches: drop the stamp and the sweep has nothing to compare."""
    monkeypatch.setattr(decisions.time, "time", lambda: 1756500000.0)
    store = decisions.record({}, "husab, what did you tell them?", "Usopp, what did you tell them?", "accept")
    assert store["decisions"][0]["at"] == 1756500000.0


def test_re_recording_a_pair_moves_its_timestamp_forward(monkeypatch):
    """record() REPLACES rather than appends so a reviewer can change their mind. The
    revision must also look NEWER, or a corrected mistake is indistinguishable from the
    verdict it replaced and the sweep skips shipping it.

    The break this catches: keep the original entry's `at` on replacement and a reviewer's
    correction of their own mistake never reaches the video."""
    monkeypatch.setattr(decisions.time, "time", lambda: 1000.0)
    store = decisions.record({}, "the flame flame fruit", "the Flame-Flame Fruit", "accept")
    monkeypatch.setattr(decisions.time, "time", lambda: 2000.0)
    store = decisions.record(store, "the flame flame fruit", "the Flame-Flame Fruit", "reject")
    assert len(store["decisions"]) == 1, "still replaced, never appended"
    assert store["decisions"][0]["verdict"] == "reject"
    assert store["decisions"][0]["at"] == 2000.0


def test_a_verdict_stored_before_timestamps_existed_still_looks_up():
    """The four live stores predate this field. An entry without `at` must keep working --
    lookup is what applies a human's verdict, and breaking it would silently discard every
    decision made before 2026-08-29.

    The break this catches: make `at` required for a match and 82 One Pace verdicts die."""
    store = {"decisions": [{"orig": "husab", "proposed": "usopp", "verdict": "accept"}]}
    hit = decisions.lookup(store, "Husab", "Usopp")
    assert hit is not None and hit["verdict"] == "accept"
    assert decisions.for_orig(store, "HUSAB")[0]["verdict"] == "accept"
