"""Unit tests for glossary_verify.py pure core (wiki HTTP + LLM are integration)."""

import json
import threading
import time

import glossary_verify as gv


def gl(**kw):
    base = {"show": "One Piece", "names": [], "phrases": [], "hard_fixes": {}, "initial_prompt": "P"}
    base.update(kw)
    return base


def test_constants_present():
    assert gv.TOPK >= 3
    assert 0 < gv.CAND_CUTOFF < 1
    assert gv.VERIFY_MODEL
    assert gv.VERIFY_WORKERS >= 1


# --- T2: candidates ----------------------------------------------------------


def test_candidates_topk_and_cutoff():
    titles = ["Spandam", "Enies Lobby", "Going Merry", "Monkey D. Luffy", "Roronoa Zoro"]
    c = gv.candidates("spandom", titles, k=3)
    assert "Spandam" in c
    assert len(c) <= 3
    assert gv.candidates("zzzzxxxxqq", titles) == []  # nothing similar -> empty


# --- T3: apply_results -------------------------------------------------------


def test_apply_never_deletes_the_original_term():
    """The 2026-08-21 bug: `lst[i] = canon` replaced in place, deleting 17 names and 6
    phrases from the live One Pace glossary into `verified`, which nothing reads."""
    g = gl(names=["Spandom", "Luffy"])
    res = {
        "Spandom": {"canonical": "Spandam", "confidence": "high", "dub_note": ""},
        "Luffy": {"canonical": "Luffy", "confidence": "high", "dub_note": ""},
    }
    out = gv.apply_results(g, res)
    assert "Spandom" in out["names"]  # <- the whole point
    assert set(out["verified"]) >= {"Spandom", "Luffy"}
    assert out["initial_prompt"] == "P"  # curated prompt preserved


def test_apply_adds_an_expansion_alongside_routed_by_shape():
    """`Doflamingo` -> `Donquixote Doflamingo` is the same entity written longer: additive,
    and multi-word so it belongs in `phrases` -- `names` feeds a per-TOKEN matcher."""
    g = gl(names=["Doflamingo"])
    out = gv.apply_results(g, {"Doflamingo": {"canonical": "Donquixote Doflamingo", "confidence": "high", "dub_note": ""}})
    assert out["names"] == ["Doflamingo"]
    assert out["phrases"] == ["Donquixote Doflamingo"]


def test_apply_flags_a_respelling_instead_of_applying_it():
    """The dangerous class. Measured on One Pace, every wrong high-confidence canonical was
    a respelling: Raftel->Ratel, Jabra->Jabari, Alabasta->Arabasta, Kaido->Kaidou."""
    g = gl(names=["Raftel", "Jabra"])
    out = gv.apply_results(
        g, {"Raftel": {"canonical": "Ratel", "confidence": "high"}, "Jabra": {"canonical": "Jabari", "confidence": "high"}}
    )
    assert out["names"] == ["Raftel", "Jabra"]  # neither applied
    assert "Ratel" not in out["names"] and "Jabari" not in out["names"]
    assert out["flagged"]["Raftel"] == {"reason": "respelling-needs-review", "canonical": "Ratel"}


def test_apply_is_idempotent_on_a_second_run():
    g = gl(names=["Doflamingo"])
    res = {"Doflamingo": {"canonical": "Donquixote Doflamingo", "confidence": "high"}}
    once = gv.apply_results(g, res)
    twice = gv.apply_results(once, res)
    assert twice["phrases"] == ["Donquixote Doflamingo"]  # not appended again
    assert twice["names"] == ["Doflamingo"]


def test_apply_flags_low_and_no_match_without_changing():
    g = gl(names=["Krieg", "Blarg"])
    res = {
        "Krieg": {"canonical": "Don Krieg", "confidence": "low", "dub_note": ""},
        "Blarg": {"canonical": "", "confidence": "none", "dub_note": ""},
    }
    out = gv.apply_results(g, res)
    assert "Krieg" in out["names"] and "Blarg" in out["names"]
    assert "Krieg" in out["flagged"] and "Blarg" in out["flagged"]


def test_apply_routes_a_dub_form_respelling_to_review():
    """`Water Seven` -> `Water 7` is a respelling, not an expansion, so it is no longer
    auto-applied. The dub form is still the right answer -- a human confirms it, and the
    original is never lost in the meantime."""
    g = gl(phrases=["Water Seven"])
    res = {"Water Seven": {"canonical": "Water 7", "confidence": "high", "dub_note": "numeral"}}
    out = gv.apply_results(g, res)
    assert "Water Seven" in out["phrases"]
    assert out["flagged"]["Water Seven"]["canonical"] == "Water 7"


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
        {"query": {"allpages": [{"title": "Spandam"}, {"title": "Enies Lobby"}]}, "continue": {"apcontinue": "Foo"}}
    )
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


# --- V2 C2: verify() parallelizes adjudicate() with ThreadPoolExecutor -----------------


def test_verify_adjudicates_terms_concurrently(monkeypatch, tmp_path):
    """4 pending terms with VERIFY_WORKERS=4 (default) must all be IN FLIGHT
    simultaneously -- a threading.Barrier(4) only releases once all 4 callers have
    reached it, which is impossible under the old serial dict-comprehension."""
    gloss_path = tmp_path / "g.json"
    gloss_path.write_text(json.dumps(gl(names=["A", "B", "C", "D"])))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["A", "B", "C", "D"])
    monkeypatch.setattr(gv, "candidates", lambda term, titles, k=gv.TOPK: [term])

    barrier = threading.Barrier(4, timeout=5)
    seen = []
    lock = threading.Lock()

    def fake_adjudicate(term, cands, show):
        barrier.wait()  # deadlocks (-> BrokenBarrierError) unless all 4 run concurrently
        with lock:
            seen.append(term)
        return {"canonical": term, "confidence": "low", "dub_note": ""}

    monkeypatch.setattr(gv, "adjudicate", fake_adjudicate)
    rep = gv.verify(str(gloss_path))
    assert rep["checked"] == 4
    assert set(seen) == {"A", "B", "C", "D"}


def test_verify_preserves_term_result_pairing_despite_completion_order(monkeypatch, tmp_path):
    """Results must map back to the TERM that produced them, not the order threads
    happen to finish in. One term's adjudicate() call sleeps (finishes last); the
    resulting glossary edit must still land on the correct original name."""
    gloss_path = tmp_path / "g.json"
    gloss_path.write_text(json.dumps(gl(names=["Spandom", "Ruffy"])))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Spandam", "Luffy"])
    canon = {"Spandom": "Spandam", "Ruffy": "Luffy"}
    monkeypatch.setattr(gv, "candidates", lambda term, titles, k=gv.TOPK: [canon[term]])

    def fake_adjudicate(term, cands, show):
        if term == "Spandom":  # submitted first, finishes LAST
            time.sleep(0.05)
        return {"canonical": cands[0], "confidence": "high", "dub_note": ""}

    monkeypatch.setattr(gv, "adjudicate", fake_adjudicate)
    rep = gv.verify(str(gloss_path))
    # Both are RESPELLINGS, so both escalate rather than apply -- and that tests the
    # pairing harder than the old assertion did: a swapped result would put Luffy under
    # Spandom, which the canonical check below catches directly.
    assert rep["applied"] == 0 and rep["escalated"] == 2
    new = json.load(open(gloss_path))
    assert "Spandom" in new["names"] and "Ruffy" in new["names"]
    assert new["flagged"]["Spandom"]["canonical"] == "Spandam"
    assert new["flagged"]["Ruffy"]["canonical"] == "Luffy"


def test_arc_categories_are_discovered_by_search(monkeypatch):
    """[S-2] Arc category naming is NOT uniform: measured 2026-08-26, `Category:Dressrosa
    Arc` does not exist, while `Dressrosa Residents`, `Dressrosa Locations` and `Dressrosa
    Saga Antagonists` do. So the categories are discovered by search, never guessed."""
    calls = []

    def fake(url):
        calls.append(url)
        return {
            "query": {
                "search": [
                    {"title": "Category:Dressrosa Residents"},
                    {"title": "Category:Dressrosa Locations"},
                    {"title": "Category:Non-Canon Dressrosa Residents"},
                ]
            }
        }

    monkeypatch.setattr(gv, "_http_json", fake)
    cats = gv.arc_categories("https://x/api.php", "Dressrosa")
    assert "Category:Dressrosa Residents" in cats
    assert "Category:Dressrosa Locations" in cats
    # non-canon material must not become canonical spellings
    assert not any("Non-Canon" in c for c in cats)
    assert "srnamespace=14" in calls[0]


def test_arc_titles_unions_the_categories_and_follows_continuation(monkeypatch):
    """Members come back paged. A truncated union would silently under-tag an arc."""
    pages = {
        "one": {"query": {"categorymembers": [{"title": "Rebecca"}, {"title": "Kyros"}]}, "continue": {"cmcontinue": "MORE"}},
        "two": {"query": {"categorymembers": [{"title": "Pica"}]}},
    }
    seen = []

    def fake(url):
        seen.append(url)
        return pages["two"] if "MORE" in url else pages["one"]

    monkeypatch.setattr(gv, "_http_json", fake)
    monkeypatch.setattr(gv, "arc_categories", lambda a, b: ["Category:Dressrosa Residents"])
    titles = gv.fetch_arc_titles("https://x/api.php", "Dressrosa")
    assert titles == {"Kyros", "Pica", "Rebecca"}


def test_arc_titles_is_empty_when_discovery_finds_nothing(monkeypatch):
    """[S-7] A season.nfo title that is not an arc -- `Gaimon` is a character -- must yield
    NOTHING rather than some other page's cast. Emptiness is the fallback trigger."""
    monkeypatch.setattr(gv, "arc_categories", lambda a, b: [])
    assert gv.fetch_arc_titles("https://x/api.php", "Gaimon") == set()


def test_arc_titles_survives_an_unreachable_wiki(monkeypatch):
    """The wiki must never stall or fail a sweep."""

    def boom(url):
        raise OSError("network down")

    monkeypatch.setattr(gv, "_http_json", boom)
    assert gv.fetch_arc_titles("https://x/api.php", "Dressrosa") == set()


def test_arc_categories_exclude_episode_and_chapter_listings(monkeypatch):
    """Measured against the live wiki 2026-08-26: searching `Dressrosa` in namespace 14
    returns `Dressrosa Arc Episodes` and `Dressrosa Arc Chapters` alongside the cast
    categories. Those hold episode and chapter PAGES, not names -- including them took the
    union from 96 to 294 entries of mostly `Episode 629`-shaped noise."""
    monkeypatch.setattr(
        gv,
        "_http_json",
        lambda url: {
            "query": {
                "search": [
                    {"title": "Category:Dressrosa Residents"},
                    {"title": "Category:Dressrosa Arc Episodes"},
                    {"title": "Category:Dressrosa Arc Chapters"},
                    {"title": "Category:Dressrosa Saga Antagonists"},
                ]
            }
        },
    )
    cats = gv.arc_categories("https://x/api.php", "Dressrosa")
    assert "Category:Dressrosa Residents" in cats
    assert "Category:Dressrosa Saga Antagonists" in cats
    assert not any("Episodes" in c or "Chapters" in c for c in cats)


def test_arc_page_links_supply_the_names_categories_miss(monkeypatch):
    """Categories alone are not sufficient and this is measured, not theoretical: neither
    `Rebecca` nor `Kyros` -- the arc's two most-mentioned characters -- appears in ANY
    `Dressrosa *` category. Rebecca is filed under `Riku Family` and `Former Princesses`.
    The arc PAGE's prose links carry them, so they are the primary source and categories
    are the supplement."""
    wikitext = (
        "{{Infobox|junk=[[Navbox Junk]]}}\n"
        "The [[Straw Hat Pirates]] arrive. [[Rebecca]] fights, and [[Kyros]] watches.\n"
        "<ref>[[Reference Junk]]</ref>\n"
    )
    monkeypatch.setattr(gv, "_http_json", lambda url: {"parse": {"wikitext": {"*": wikitext}}})
    names = gv.arc_page_links("https://x/api.php", "Dressrosa")
    assert {"Rebecca", "Kyros", "Straw Hat Pirates"} <= names
    # templates and refs are stripped: navbox pollution made prop=links unusable
    assert "Navbox Junk" not in names
    assert "Reference Junk" not in names


def test_arc_page_links_is_empty_when_the_page_is_missing(monkeypatch):
    def boom(url):
        raise OSError("no such page")

    monkeypatch.setattr(gv, "_http_json", boom)
    assert gv.arc_page_links("https://x/api.php", "Nonesuch") == set()


def test_a_character_named_season_resolves_to_nothing(monkeypatch):
    """[S-7], measured: `Gaimon` is a One Pace season.nfo title AND a character page. An
    earlier cut fell back to the bare title when `<arc> Arc` was missing, resolved the
    character page, and harvested 48 entities from it -- a wrong-but-resolved page passing
    as a cast. Only `<arc> Arc` counts; anything else is no resolution."""
    seen = []

    def fake(url):
        seen.append(url)
        if "Gaimon%20Arc" in url or "Gaimon+Arc" in url:
            raise OSError("no such page")
        raise AssertionError("must not fall back to the bare title")

    monkeypatch.setattr(gv, "_http_json", fake)
    assert gv.arc_page_links("https://x/api.php", "Gaimon") == set()
    assert len(seen) == 1
