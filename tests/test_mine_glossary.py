"""Unit tests for mine_glossary.py's mine_text() (T19): the pure counting/tracking pass
over a block of subtitle plaintext that main() runs per-episode, before its own
COMMON-word + MIN_COUNT + already-known filtering of the accumulated results.

DIVERGENCE from specs/v1-polish/tasks.md T19 / spec.md Phase 4 ("word in the COMMON
deny-set -> ignored"): mine_text() itself does NOT consult COMMON at all -- it counts
and tracks every capitalized candidate word unconditionally. The COMMON exclusion is
applied downstream in main(): `t.lower() not in COMMON` (mine_glossary.py). The case
below documents mine_text()'s real (unfiltered) behavior for a COMMON word instead of
asserting the false claim that mine_text() ignores it.
"""
import mine_glossary


def test_mine_text():
    # 1. capitalized word mid-sentence -> counted + tracked in midsentence
    counter, mid = {}, set()
    mine_glossary.mine_text("I saw Luffy today.", counter, mid)
    assert counter == {"Luffy": 1}
    assert mid == {"Luffy"}

    # 2. capitalized word at sentence start -> counted, NOT tracked in midsentence
    counter, mid = {}, set()
    mine_glossary.mine_text("Zoro drew his blade.", counter, mid)
    assert counter == {"Zoro": 1}
    assert mid == set()

    # 3. lowercase word -> ignored entirely (not counted, not tracked)
    counter, mid = {}, set()
    mine_glossary.mine_text("he saw luffy today", counter, mid)
    assert counter == {}
    assert mid == set()

    # 4. word in the COMMON deny-set -> mine_text() does NOT filter it (see divergence
    #    note above); it's counted/tracked like any other capitalized candidate. The
    #    downstream `t.lower() not in COMMON` exclusion in main() is what actually drops it.
    assert "doctor" in mine_glossary.COMMON
    counter, mid = {}, set()
    mine_glossary.mine_text("I saw the Doctor again.", counter, mid)
    assert counter == {"Doctor": 1}
    assert mid == {"Doctor"}

    # 5. word shorter than 3 chars -> ignored (the word-candidate regex itself requires
    #    >= 3 characters, before the capitalization check is even applied)
    counter, mid = {}, set()
    mine_glossary.mine_text("I saw Oz today", counter, mid)
    assert counter == {}
    assert mid == set()
