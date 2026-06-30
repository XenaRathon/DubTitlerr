"""Unit tests for glossary_verify.py pure core (wiki HTTP + LLM are integration)."""
import glossary_verify as gv


def gl(**kw):
    base = {"show": "One Piece", "names": [], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}
    base.update(kw)
    return base


def test_constants_present():
    assert gv.TOPK >= 3
    assert 0 < gv.CAND_CUTOFF < 1
    assert gv.VERIFY_MODEL


# --- T2: candidates ----------------------------------------------------------

def test_candidates_topk_and_cutoff():
    titles = ["Spandam", "Enies Lobby", "Going Merry", "Monkey D. Luffy", "Roronoa Zoro"]
    c = gv.candidates("spandom", titles, k=3)
    assert "Spandam" in c
    assert len(c) <= 3
    assert gv.candidates("zzzzxxxxqq", titles) == []      # nothing similar -> empty


# --- T3: apply_results -------------------------------------------------------

def test_apply_high_confidence_corrects_name_and_marks_verified():
    g = gl(names=["Spandom", "Luffy"])
    res = {"Spandom": {"canonical": "Spandam", "confidence": "high", "dub_note": ""},
           "Luffy": {"canonical": "Luffy", "confidence": "high", "dub_note": ""}}
    out = gv.apply_results(g, res)
    assert "Spandam" in out["names"] and "Spandom" not in out["names"]
    assert set(out["verified"]) >= {"Spandom", "Luffy"}
    assert out["initial_prompt"] == "P"                   # curated prompt preserved


def test_apply_flags_low_and_no_match_without_changing():
    g = gl(names=["Krieg", "Blarg"])
    res = {"Krieg": {"canonical": "Don Krieg", "confidence": "low", "dub_note": ""},
           "Blarg": {"canonical": "", "confidence": "none", "dub_note": ""}}
    out = gv.apply_results(g, res)
    assert "Krieg" in out["names"] and "Blarg" in out["names"]
    assert "Krieg" in out["flagged"] and "Blarg" in out["flagged"]


def test_apply_prefers_dub_form():
    g = gl(phrases=["Water Seven"])
    res = {"Water Seven": {"canonical": "Water 7", "confidence": "high", "dub_note": "numeral"}}
    out = gv.apply_results(g, res)
    assert "Water 7" in out["phrases"] and "Water Seven" not in out["phrases"]


def test_apply_preserves_unknown_fields():
    g = gl(names=["Luffy"], hard_fixes={"ruffy": "Luffy"}, wiki="https://x.fandom.com/api.php")
    out = gv.apply_results(g, {"Luffy": {"canonical": "Luffy", "confidence": "high", "dub_note": ""}})
    assert out["hard_fixes"] == {"ruffy": "Luffy"} and out["wiki"].endswith("api.php")


# --- T4: pending_terms (incremental) -----------------------------------------

def test_pending_terms_skips_verified():
    g = gl(names=["Luffy", "Zoro"], phrases=["Grand Line"], verified=["Luffy"])
    p = gv.pending_terms(g)
    assert "Luffy" not in p and "Zoro" in p and "Grand Line" in p


# --- T5: build_adjudication_prompt -------------------------------------------

def test_prompt_has_term_candidates_and_dub_rule():
    p = gv.build_adjudication_prompt("spandom", ["Spandam", "Spandine"], "One Piece")
    assert "spandom" in p and "Spandam" in p
    assert "dub" in p.lower()
    assert "canonical" in p.lower()


# --- T6: wiki I/O pure helpers -----------------------------------------------

def test_wiki_candidates_from_messy_title():
    cands = gv.wiki_candidates("One Piece (1999) {tvdb-81797}")
    assert any("onepiece.fandom.com" in c for c in cands)
    assert all(c.endswith("/api.php") for c in cands)


def test_normalize_api_handles_bases_and_paths():
    assert gv.normalize_api("https://onepiece.fandom.com") == "https://onepiece.fandom.com/api.php"
    assert gv.normalize_api("https://onepiece.fandom.com/api.php").endswith("/api.php")
    assert gv.normalize_api("https://onepiece.fandom.com/wiki/Spandam").endswith("fandom.com/api.php")


def test_allpages_url_and_parse():
    u = gv.allpages_url("https://x.fandom.com/api.php")
    assert "list=allpages" in u and "apnamespace=0" in u
    titles, cont = gv.parse_allpages(
        {"query": {"allpages": [{"title": "Spandam"}, {"title": "Enies Lobby"}]},
         "continue": {"apcontinue": "Foo"}})
    assert titles == ["Spandam", "Enies Lobby"] and cont == "Foo"
    t2, c2 = gv.parse_allpages({"query": {"allpages": [{"title": "A"}]}})
    assert t2 == ["A"] and c2 is None


# --- T7: LLM reply parsing ---------------------------------------------------

def test_parse_adjudication_clean_json():
    d = gv.parse_adjudication('{"canonical": "Spandam", "confidence": "high", "dub_note": ""}')
    assert d["canonical"] == "Spandam" and d["confidence"] == "high"


def test_parse_adjudication_json_with_prose():
    d = gv.parse_adjudication('Sure!\n{"canonical":"Water 7","confidence":"high","dub_note":"numeral"}\nDone')
    assert d["canonical"] == "Water 7" and d["dub_note"] == "numeral"


def test_parse_adjudication_garbage_is_none():
    assert gv.parse_adjudication("no json here")["confidence"] == "none"


def test_parse_adjudication_bad_confidence_defaults_low():
    d = gv.parse_adjudication('{"canonical":"X","confidence":"pretty sure"}')
    assert d["confidence"] == "low"
