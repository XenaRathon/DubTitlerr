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
