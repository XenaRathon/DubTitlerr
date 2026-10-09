"""Phase 1 of the glossary-stage bake-off: `tools/glossary_bakeoff.py build-set`.

Everything here runs on small synthetic fixtures built in tmp_path -- the real glossary snapshot is
git-excluded and must never be copied into a test. The acceptance criterion is (a): the candidate
list in items.jsonl is exactly what the PRODUCTION `glossary_verify.candidates` returns."""

import json
import re
import time

import pytest

import acquire_cache
import glossary_verify as gv
import tools.glossary_bakeoff as gb

ALPHA = {
    "show": "Alpha Show",
    "_curated": True,
    "names": ["Zoro", "Luffy", "Nami", "Sanji", "Chopper"],
    "phrases": ["Straw Hat Pirates"],
    "verified": ["Nami"],
    "flagged": {"Luffy": "no-match", "Chopper": {"reason": "respelling-needs-review", "canonical": "Chopperman"}},
    "hard_fixes": {"zorro": "Zoro"},
}
ALPHA_TITLES = ["Roronoa Zoro", "Zoro", "Monkey D. Luffy", "Luffy", "Nami", "Straw Hat Pirates", "Chopperman", "Unrelated Title"]
BETA = {"show": "Beta Show", "names": ["Kaido", "qqqzzz"], "phrases": []}  # not curated
BETA_TITLES = ["Kaidou", "Kaido"]


def _put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def _wiki(wiki_dir, show, titles):
    cache = {"api": "https://x/api.php", "fetched_at": 1, "titles": titles}
    _put(wiki_dir / (re.sub(r"[^A-Za-z0-9]+", "_", show) + ".json"), cache)


@pytest.fixture
def data(tmp_path):
    g, w = tmp_path / "glossaries", tmp_path / "wiki_cache"
    _put(g / "Alpha Show.json", ALPHA)
    _put(g / "Alpha Show.lastrun.json", {"junk": True})  # ignored
    _put(g / "Alpha Show.acquire-cache.json", {"Zoroo": {"Zoro": {"same_entity": True, "confidence": "high"}}, "Bad": "notadict"})
    _put(g / "Beta Show.json", BETA)
    _put(g / "Gamma Show.json", {"show": "Gamma Show", "names": ["Foo"], "phrases": []})  # no wiki cache
    _put(g / "Delta Show.json", "{ this is not json")  # malformed
    _put(g / "Epsilon Show.json", {"show": "Epsilon Show", "names": ["Bar"], "phrases": []})
    _wiki(w, "Alpha Show", ALPHA_TITLES)
    _wiki(w, "Beta Show", BETA_TITLES)
    _wiki(w, "Epsilon Show", [])  # empty titles
    return g, w


def _build(tmp_path, g, w, *extra, name="items.jsonl"):
    out = tmp_path / name
    code = gb.main(["build-set", "--glossaries", str(g), "--wiki-cache", str(w), "--out", str(out), *extra])
    items = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []
    return code, items, out


def _verify(items, show, term):
    return next(i for i in items if i["stage"] == "verify" and i["show"] == show and i["term"] == term)


def test_candidate_lists_equal_the_production_function(tmp_path, data, capsys):
    g, w = data
    code, items, _ = _build(tmp_path, g, w)
    assert code == 0
    checked = 0
    for show, titles in (("Alpha Show", ALPHA_TITLES), ("Beta Show", BETA_TITLES)):
        for it in (i for i in items if i["stage"] == "verify" and i["show"] == show):
            assert [c["title"] for c in it["candidates"]] == gv.candidates(it["term"], titles)
            assert all(0.62 <= c["score"] <= 1 for c in it["candidates"])
            assert [c["score"] for c in it["candidates"]] == sorted((c["score"] for c in it["candidates"]), reverse=True)
            checked += 1
    assert checked == 8  # 6 Alpha terms + 2 Beta terms


def test_a_term_with_no_candidates_is_kept_as_a_no_call_control(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    it = _verify(items, "Beta Show", "qqqzzz")
    assert it["candidates"] == [] and it["no_call"] is True and it["gold"] is None
    assert _verify(items, "Beta Show", "Kaido")["no_call"] is False


def test_items_say_where_the_term_came_from(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    luffy = _verify(items, "Alpha Show", "Luffy")
    assert luffy["list"] == "names" and luffy["flagged"] == "no-match" and luffy["verified"] is False
    assert _verify(items, "Alpha Show", "Nami")["verified"] is True  # a verify --force would still send it
    assert _verify(items, "Alpha Show", "Straw Hat Pirates")["list"] == "phrases"
    assert _verify(items, "Alpha Show", "Chopper")["flagged"]["reason"] == "respelling-needs-review"


def test_curated_show_gold_only_when_the_canonical_is_a_candidate(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    zoro = _verify(items, "Alpha Show", "Zoro")
    assert zoro["gold"] == "Zoro" and zoro["gold_source"] == "curated"  # the exact term wins over "Roronoa Zoro"
    luffy = _verify(items, "Alpha Show", "Luffy")
    assert luffy["gold"] == "Luffy"  # "Monkey D. Luffy" is not a curated name
    sanji = _verify(items, "Alpha Show", "Sanji")
    assert sanji["candidates"] == [] and sanji["gold"] is None  # no candidate at all
    chopper = _verify(items, "Alpha Show", "Chopper")
    assert [c["title"] for c in chopper["candidates"]] == ["Chopperman"]
    assert chopper["gold"] is None  # candidates exist but none is a curated canonical
    assert "gold_source" not in chopper


def test_a_non_curated_show_never_gets_gold(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    beta = [i for i in items if i["stage"] == "verify" and i["show"] == "Beta Show"]
    assert beta and all(i["gold"] is None and "gold_source" not in i for i in beta)


def test_acquire_pairs_carry_the_historical_verdict_and_no_quotes(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    pairs = [i for i in items if i["stage"] == "acquire"]
    assert len(pairs) == 1  # the malformed pair entry is skipped
    p = pairs[0]
    assert (p["show"], p["variant"], p["canonical"]) == ("Alpha Show", "Zoroo", "Zoro")
    assert p["historical"] == acquire_cache.escalation_for(acquire_cache.load(str(g / "Alpha Show.json")), "Zoroo", "Zoro")
    assert p["historical"] == {"same_entity": True, "confidence": "high"} and p["quotes"] is None


def test_a_rerun_is_byte_identical(tmp_path, data):
    g, w = data
    _, _, first = _build(tmp_path, g, w, name="a.jsonl")
    _, _, second = _build(tmp_path, g, w, name="b.jsonl")
    assert first.read_bytes() == second.read_bytes() and first.read_bytes()
    assert first.read_bytes().endswith(b"\n")


def test_unicode_is_written_unescaped(tmp_path):
    g, w = tmp_path / "g", tmp_path / "w"
    _put(g / "Uni.json", {"show": "Uni", "names": ["Ōtsutsuki"], "phrases": []})
    _wiki(w, "Uni", ["Ōtsutsuki Clan"])
    _, items, out = _build(tmp_path, g, w)
    assert "Ōtsutsuki" in out.read_text(encoding="utf-8") and items[0]["candidates"]


def test_malformed_and_empty_inputs_are_reported_and_skipped(tmp_path, data, capsys):
    g, w = data
    code, items, _ = _build(tmp_path, g, w)
    out = capsys.readouterr().out
    assert code == 0
    assert "Delta Show" in out and "malformed" in out
    assert "Epsilon Show" in out and "empty" in out
    assert not [i for i in items if i["show"] in ("Delta Show", "Epsilon Show")]


def test_a_show_with_no_wiki_cache_makes_no_verify_items_and_is_listed(tmp_path, data, capsys):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    out = capsys.readouterr().out
    assert not [i for i in items if i["show"] == "Gamma Show"]
    assert "Gamma Show" in out and "no wiki cache" in out


def test_show_filter_keeps_only_matching_shows(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w, "--show", "beta")
    assert items and {i["show"] for i in items} == {"Beta Show"}
    _, items, _ = _build(tmp_path, g, w, "--show", "beta", "alpha", name="two.jsonl")
    assert {i["show"] for i in items} == {"Alpha Show", "Beta Show"}


def test_the_summary_has_per_show_counts_and_totals(tmp_path, data, capsys):
    g, w = data
    _build(tmp_path, g, w)
    out = capsys.readouterr().out
    alpha = next(line for line in out.splitlines() if line.startswith("Alpha Show"))
    assert "6" in alpha and "5" in alpha  # 6 verify items, 5 with candidates
    assert "TOTAL" in out and "skipped" in out.lower()


def test_building_the_set_makes_no_network_call(tmp_path, data, monkeypatch):
    import http.client
    import socket
    import urllib.request

    def no_net(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", no_net)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(gv, "_http_json", no_net)
    g, w = data
    code, items, _ = _build(tmp_path, g, w)
    assert code == 0 and items


def test_the_cache_file_mapping_is_the_one_fetch_titles_reads(tmp_path, monkeypatch):
    """fetch_titles has no separate mapping function, so the filename rule is mirrored; prove it by letting the
    production reader find the file the mirrored path points at."""
    show = "Weird Show (2020) {tvdb-1}"
    w = tmp_path / "w"
    w.mkdir()
    path = gb.wiki_cache_path(str(w), show)
    _put(type(w)(path), {"api": "https://x/api.php", "fetched_at": time.time(), "titles": ["T1", "T2"]})
    monkeypatch.setattr(gv, "CACHE_DIR", str(w))
    monkeypatch.setattr(gv, "_http_json", lambda url: pytest.fail("must read the cache"))
    assert gv.fetch_titles("https://x/api.php", show) == ["T1", "T2"]


def test_unknown_flags_and_missing_directories_exit_2(tmp_path, data):
    g, w = data
    with pytest.raises(SystemExit) as e:
        gb.main(["build-set", "--glossaries", str(g), "--wiki-cache", str(w), "--out", str(tmp_path / "o"), "--bogus"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        gb.main(["build-set", "--glossaries", str(tmp_path / "nope"), "--wiki-cache", str(w), "--out", str(tmp_path / "o")])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        gb.main([])  # a subcommand is required
    assert e.value.code == 2


# =====================================================================================
# `run`: put the item set to one arm. Fake transports only; nothing here touches a network.
# =====================================================================================

import acquire_cache as _ac  # noqa: E402,F401
import common  # noqa: E402
import glossary_acquire as ga  # noqa: E402
import tools.bakeoff as bakeoff  # noqa: E402
import tools.decision_client as dc  # noqa: E402

KEY = "sk-SENTINEL-RUN-KEY-777"


def _cands(*titles):
    return [{"title": t, "score": 0.9} for t in titles]


def _vitem(term, titles, gold=None, show="Alpha Show"):
    return {
        "id": f"verify:{show}:{term}", "stage": "verify", "show": show, "term": term, "list": "names", "verified": False,
        "flagged": None, "acquired": False, "candidates": _cands(*titles), "no_call": not titles, "gold": gold,
    }  # fmt: skip


def _aitem(variant, canonical, quotes=None, show="Alpha Show"):
    return {
        "id": f"acquire:{show}:{variant}|{canonical}", "stage": "acquire", "show": show, "variant": variant,
        "canonical": canonical, "historical": {"same_entity": True, "confidence": "high"}, "quotes": quotes,
    }  # fmt: skip


@pytest.fixture
def items_file(tmp_path):
    items = [
        _vitem("Zoro", ["Zoro", "Roronoa Zoro"], gold="Zoro"),
        _vitem("Luffy", ["Luffy", "Monkey D. Luffy"]),
        _vitem("qqq", []),
        _aitem("Zoroo", "Zoro"),
        _aitem("Nammi", "Nami", quotes={"variant": ["Nammi said hi"], "canonical": ["Nami waved"]}),
    ]
    p = tmp_path / "items.jsonl"
    p.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    return p


def _run(tmp_path, items, arm, *extra, out="res/out.jsonl"):
    outp = tmp_path / out
    code = gb.main(["run", "--items", str(items), "--arm", arm, "--out", str(outp), *extra])
    rows = [json.loads(line) for line in outp.read_text(encoding="utf-8").splitlines()] if outp.exists() else []
    return code, rows, outp


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(gb, "_sleep", lambda s: None)
    monkeypatch.setenv("LONGCATAI_API_KEY", KEY)
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    monkeypatch.setenv("OPENROUTER_JEV_API_KEY", KEY)


def _fake_local(monkeypatch, reply):
    calls = []

    def fake(prompt, **kw):
        calls.append((prompt, kw))
        return reply(prompt) if callable(reply) else reply

    monkeypatch.setattr(common, "llm_chat", fake)
    return calls


def test_the_registry_names_every_arm_with_its_endpoint_and_key():
    r = gb.ARMS
    assert set(r) == {
        "qwen-local", "longcat-2.0", "longcat-2.5", "nemotron-super",
        "mercury-decide", "span-01-lite", "solar-decide-flash", "pplx-decider", "gpt-6-luna-decisions", "jev",
    }  # fmt: skip
    assert r["longcat-2.0"].url == "https://api.longcat.chat/openai/v1/chat/completions"
    assert r["longcat-2.0"].key_env == "LONGCATAI_API_KEY" and r["longcat-2.0"].extra_body == {"thinking": {"type": "disabled"}}
    assert r["nemotron-super"].key_env == "NVIDIA_API_KEY"
    assert r["nemotron-super"].extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert {r[n].key_env for n in r if r[n].kind == "decision"} == {"OPENROUTER_JEV_API_KEY"}
    assert all(r[n].model in dc.ALLOWED_MODELS for n in r if r[n].kind == "decision")
    assert r["qwen-local"].third_party is False and all(r[n].third_party for n in r if n != "qwen-local")


def test_qwen_local_goes_through_common_llm_chat_with_the_production_prompt_and_parse(tmp_path, items_file, monkeypatch):
    calls = _fake_local(monkeypatch, 'Sure!\n{"canonical": "Zoro", "confidence": "high", "dub_note": "x"}\nthanks')
    code, rows, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    assert code == 0
    zoro = next(r for r in rows if r["id"] == "verify:Alpha Show:Zoro")
    assert zoro["parsed"] == {"canonical": "Zoro", "confidence": "high"} and zoro["error"] is None
    assert zoro["order"] == "fwd" and zoro["arm"] == "qwen-local" and "Sure!" in zoro["raw"] and zoro["latency_s"] >= 0
    prompt, kw = calls[0]
    assert prompt == gv.build_adjudication_prompt("Zoro", ["Zoro", "Roronoa Zoro"], "Alpha Show")
    assert kw["backend"] == gv.VERIFY_BACKEND and kw["model"] == gv.VERIFY_MODEL and kw["first_line"] is False
    assert len(calls) == 2  # Zoro and Luffy; the no-call control is never sent


def test_qwen_local_with_no_answer_is_an_error_row_not_a_none_pick(tmp_path, items_file, monkeypatch):
    _fake_local(monkeypatch, "")
    _, rows, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    row = next(r for r in rows if r["id"].endswith(":Zoro"))
    assert row["error"] and row["parsed"] is None


def test_qwen_local_acquire_uses_the_production_merge_prompt_even_without_quotes(tmp_path, items_file, monkeypatch):
    calls = _fake_local(monkeypatch, '{"same_entity": true, "confidence": "high"}')
    _, rows, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "acquire")
    assert [r["id"] for r in rows] == ["acquire:Alpha Show:Zoroo|Zoro", "acquire:Alpha Show:Nammi|Nami"]
    assert rows[0]["parsed"] == {"same_entity": True, "confidence": "high"}
    assert calls[0][0] == ga.build_merge_prompt("Zoroo", "Zoro", [], [], "Alpha Show")
    assert calls[1][0] == ga.build_merge_prompt("Nammi", "Nami", ["Nammi said hi"], ["Nami waved"], "Alpha Show")


def _fake_openai(monkeypatch, reply, seen=None):
    def fake(url, model, prompt, key_env, extra_body=None, usage_sink=None, max_tokens=1024, delay=0.0, first_line=True):
        if seen is not None:
            seen.append(
                {"url": url, "model": model, "prompt": prompt, "key_env": key_env, "extra": extra_body, "first_line": first_line}
            )
        out = reply(prompt) if callable(reply) else reply
        if usage_sink is not None:
            usage_sink.append({"prompt_tokens": 40, "completion_tokens": 9, "cached_tokens": 32})
        return out, 0.25

    monkeypatch.setattr(bakeoff, "ask_openai", fake)


def test_a_text_arm_uses_the_registry_endpoint_the_production_prompt_and_parse(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_openai(monkeypatch, '{\n "canonical": "Roronoa Zoro",\n "confidence": "low"\n}', seen)
    _, rows, _ = _run(tmp_path, items_file, "longcat-2.0", "--stage", "verify")
    arm = gb.ARMS["longcat-2.0"]
    assert seen[0]["url"] == arm.url and seen[0]["model"] == arm.model and seen[0]["key_env"] == "LONGCATAI_API_KEY"
    assert seen[0]["extra"] == {"thinking": {"type": "disabled"}} and seen[0]["first_line"] is False
    assert seen[0]["prompt"] == gv.build_adjudication_prompt("Zoro", ["Zoro", "Roronoa Zoro"], "Alpha Show")
    row = rows[0]
    assert row["parsed"] == {"canonical": "Roronoa Zoro", "confidence": "low"}
    assert row["usage"] == {"prompt_tokens": 40, "completion_tokens": 9, "cached_tokens": 32} and row["latency_s"] == 0.25


@pytest.mark.parametrize("bad", ["<ERROR HTTP 429>", "<ERROR rate-limited (HTTP 429)>", "<EMPTY no content>"])
def test_a_text_arm_failure_is_an_error_row_with_no_pick(tmp_path, items_file, monkeypatch, bad):
    _fake_openai(monkeypatch, bad)
    _, rows, _ = _run(tmp_path, items_file, "nemotron-super", "--stage", "verify")
    sent = [r for r in rows if not r.get("local")]
    assert len(sent) == 2 and all(r["parsed"] is None and r["error"] for r in sent)


def test_unparseable_text_is_scored_as_the_production_parser_scores_it(tmp_path, items_file, monkeypatch):
    """Parsing quality is part of the score: prose with no JSON parses to production's `none`, not to an error."""
    _fake_openai(monkeypatch, "I think it is Zoro.")
    _, rows, _ = _run(tmp_path, items_file, "longcat-2.5", "--stage", "verify")
    assert rows[0]["parsed"] == {"canonical": "", "confidence": "none"} and rows[0]["error"] is None


def test_third_party_arms_skip_acquire_items_that_have_no_quotes_and_say_so(tmp_path, items_file, monkeypatch, capsys):
    seen = []
    _fake_openai(monkeypatch, '{"same_entity": true, "confidence": "high"}', seen)
    _, rows, _ = _run(tmp_path, items_file, "longcat-2.0", "--stage", "acquire")
    assert [r["id"] for r in rows] == ["acquire:Alpha Show:Nammi|Nami"]  # the one with quotes
    assert seen[0]["prompt"] == ga.build_merge_prompt("Nammi", "Nami", ["Nammi said hi"], ["Nami waved"], "Alpha Show")
    assert rows[0]["parsed"] == {"same_entity": True, "confidence": "high"}
    assert "skipped (no quotes): 1" in capsys.readouterr().out


def _fake_decide(monkeypatch, answer, seen=None):
    def fake(model, state, questions, key_env, **kw):
        if seen is not None:
            seen.append({"model": model, "state": state, "questions": questions, "key_env": key_env})
        ans = answer(model, state, questions) if callable(answer) else answer
        return dc.DecisionResult(answers=ans, usage={"input_tokens": 5, "output_tokens": 1}, latency_s=0.5, model=model)

    monkeypatch.setattr(dc, "decide", fake)


def _choice(opt, probs=None, conf=0.9):
    return {"pick": {"type": "choice", "choice": opt, "probabilities": probs or {opt: 1.0}, "confidence": conf}}


def test_a_decision_arm_asks_one_choice_question_and_stores_the_raw_answer(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_decide(monkeypatch, _choice("c2", {"c1": 0.1, "c2": 0.8, "none": 0.1}, 0.77), seen)
    _, rows, _ = _run(tmp_path, items_file, "mercury-decide", "--stage", "verify")
    q = seen[0]["questions"]["pick"]
    assert q["type"] == "choice" and q["criteria"] == {
        "c1": "Zoro",
        "c2": "Roronoa Zoro",
        "none": "no candidate is the same named entity",
    }
    assert seen[0]["state"] == {"show": "Alpha Show", "term": "Zoro"} and seen[0]["key_env"] == "OPENROUTER_JEV_API_KEY"
    assert seen[0]["model"] == "inception/mercury-decide:free"
    row = rows[0]
    assert row["parsed"] == {
        "choice": "c2",
        "canonical": "Roronoa Zoro",
        "probabilities": {"c1": 0.1, "c2": 0.8, "none": 0.1},
        "confidence": 0.77,
    }  # fmt: skip  -- no threshold applied here
    assert row["raw"]["options"]["c2"] == "Roronoa Zoro" and row["usage"] == {"input_tokens": 5, "output_tokens": 1}


def test_a_decision_arm_none_choice_maps_to_no_canonical(tmp_path, items_file, monkeypatch):
    _fake_decide(monkeypatch, _choice("none"))
    _, rows, _ = _run(tmp_path, items_file, "jev", "--stage", "verify")
    assert rows[0]["parsed"]["choice"] == "none" and rows[0]["parsed"]["canonical"] == ""


def test_reverse_shows_the_candidates_reversed_and_maps_the_answer_back_to_the_title(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_decide(monkeypatch, _choice("c1"), seen)
    _, rows, _ = _run(tmp_path, items_file, "solar-decide-flash", "--stage", "verify", "--reverse")
    assert list(seen[0]["questions"]["pick"]["criteria"].values())[:2] == ["Roronoa Zoro", "Zoro"]
    assert rows[0]["order"] == "rev" and rows[0]["parsed"]["canonical"] == "Roronoa Zoro"  # c1 is the LAST original candidate


def test_reverse_for_a_text_arm_reverses_the_list_in_the_prompt(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_openai(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}', seen)
    _run(tmp_path, items_file, "longcat-2.0", "--stage", "verify", "--reverse")
    assert seen[0]["prompt"] == gv.build_adjudication_prompt("Zoro", ["Roronoa Zoro", "Zoro"], "Alpha Show")


def test_reverse_skips_acquire_items(tmp_path, items_file, monkeypatch):
    _fake_local(monkeypatch, '{"same_entity": true, "confidence": "high"}')
    _, rows, _ = _run(tmp_path, items_file, "qwen-local", "--reverse")
    assert rows and all(r["id"].startswith("verify:") and r["order"] == "rev" for r in rows)


def test_span_01_lite_is_run_per_candidate_as_a_noul_question(tmp_path, items_file, monkeypatch):
    seen = []
    scores = {"Zoro": 0.9, "Roronoa Zoro": 0.4}

    def answer(model, state, questions):
        title = state["output"]["content"]
        return {next(iter(questions)): scores[title]}

    _fake_decide(monkeypatch, answer, seen)
    _, rows, _ = _run(tmp_path, items_file, "span-01-lite", "--stage", "verify", "--only", "gold")
    assert len(seen) == 2 and {s["model"] for s in seen} == {"respan/span-01-lite"}
    q = next(iter(seen[0]["questions"].values()))
    assert q["type"] == "noul" and set(q["criteria"]) == {"true", "false"} and "same named entity" in q["instructions"]
    assert seen[0]["state"]["input"][0]["role"] == "user" and "Zoro" in seen[0]["state"]["input"][0]["content"]
    assert seen[0]["state"]["output"] == {"role": "assistant", "content": "Zoro"}
    assert rows[0]["parsed"] == {"scores": {"Zoro": 0.9, "Roronoa Zoro": 0.4}}


def test_a_decision_failure_is_an_error_row_with_no_pick(tmp_path, items_file, monkeypatch):
    def boom(*a, **k):
        raise dc.DecisionHTTPError(429)

    monkeypatch.setattr(dc, "decide", boom)
    _, rows, _ = _run(tmp_path, items_file, "pplx-decider", "--stage", "verify")
    sent = [r for r in rows if not r.get("local")]
    assert len(sent) == 2 and all(r["error"] == "HTTP 429" and r["parsed"] is None for r in sent)


def test_an_unexpected_exception_records_only_its_class_never_its_text(tmp_path, items_file, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError(f"Invalid header value b'Bearer {KEY}'")

    monkeypatch.setattr(dc, "decide", boom)
    _, rows, outp = _run(tmp_path, items_file, "gpt-6-luna-decisions", "--stage", "verify")
    assert rows[0]["error"] == "RuntimeError"
    out = capsys.readouterr()
    assert KEY not in outp.read_text(encoding="utf-8") + out.out + out.err


def test_run_is_resumable_and_does_not_resend_finished_rows(tmp_path, items_file, monkeypatch):
    calls = _fake_local(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
    _, rows, outp = _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    first = len(calls)
    _, rows2, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    assert len(calls) == first and len(rows2) == len(rows)


def test_errored_rows_are_retried_only_with_retry_errors(tmp_path, items_file, monkeypatch):
    state = {"fail": True}

    def reply(prompt):
        return "" if state["fail"] and "Zoro" in prompt.split("\n")[1] else '{"canonical": "Luffy", "confidence": "high"}'

    calls = _fake_local(monkeypatch, reply)
    _, rows, outp = _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    assert sum(1 for r in rows if r["error"]) == 1
    state["fail"] = False
    n = len(calls)
    _, rows2, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    assert len(calls) == n and len(rows2) == len(rows)  # errored rows are NOT retried by default
    _, rows3, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "verify", "--retry-errors")
    assert len(calls) == n + 1  # exactly the one errored item
    assert rows3[-1]["error"] is None and rows3[-1]["id"].endswith(":Zoro")


def test_a_torn_last_line_does_not_stop_a_resume(tmp_path, items_file, monkeypatch):
    calls = _fake_local(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
    outp = tmp_path / "res" / "out.jsonl"
    outp.parent.mkdir()
    outp.write_text('{"id": "verify:Alpha Show:Zoro", "arm": "qwen-local", "order": "fwd", "error": null, "par', encoding="utf-8")
    code = gb.main(["run", "--items", str(items_file), "--arm", "qwen-local", "--out", str(outp), "--stage", "verify"])
    assert code == 0 and calls
    lines = outp.read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith('"par')  # the torn line stays as it was, on its own line
    assert all(json.loads(line)["arm"] == "qwen-local" for line in lines[1:])  # the new rows are whole


def test_no_call_items_are_answered_locally_and_never_sent(tmp_path, items_file, monkeypatch):
    sent = []
    _fake_decide(monkeypatch, _choice("c1"), sent)
    _, rows, _ = _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "nocall")
    assert not sent and len(rows) == 1
    assert rows[0]["id"].endswith(":qqq") and rows[0]["local"] is True
    assert rows[0]["parsed"] == {"canonical": "", "confidence": "none"} and rows[0]["error"] is None


def test_only_gold_sends_just_the_items_with_a_gold_label(tmp_path, items_file, monkeypatch):
    sent = []
    _fake_decide(monkeypatch, _choice("c1"), sent)
    _, rows, _ = _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    assert [r["id"] for r in rows] == ["verify:Alpha Show:Zoro"] and len(sent) == 1


def test_stage_acquire_runs_no_verify_items(tmp_path, items_file, monkeypatch):
    _fake_local(monkeypatch, '{"same_entity": false, "confidence": "low"}')
    _, rows, _ = _run(tmp_path, items_file, "qwen-local", "--stage", "acquire")
    assert rows and all(r["id"].startswith("acquire:") for r in rows)


def _many(tmp_path, n):
    p = tmp_path / "many.jsonl"
    p.write_text("".join(json.dumps(_vitem(f"T{i}", [f"T{i}x"])) + "\n" for i in range(n)), encoding="utf-8")
    return p


def test_sample_is_deterministic_given_the_seed_and_keeps_file_order(tmp_path, monkeypatch):
    _fake_local(monkeypatch, '{"canonical": "", "confidence": "none"}')
    many = _many(tmp_path, 40)
    ids = []
    for i, seed in enumerate(("1", "1", "2")):
        _, rows, _ = _run(tmp_path, many, "qwen-local", "--sample", "10", "--seed", seed, out=f"s{i}.jsonl")
        ids.append([r["id"] for r in rows])
    assert ids[0] == ids[1] and len(ids[0]) == 10 and ids[0] != ids[2]
    assert ids[0] == sorted(ids[0], key=lambda s: int(s.rsplit("T", 1)[1]))  # original order preserved


def test_limit_takes_the_first_n(tmp_path, monkeypatch):
    _fake_local(monkeypatch, '{"canonical": "", "confidence": "none"}')
    _, rows, _ = _run(tmp_path, _many(tmp_path, 10), "qwen-local", "--limit", "3")
    assert [r["id"].rsplit(":", 1)[1] for r in rows] == ["T0", "T1", "T2"]


def test_delay_sits_between_sent_calls_only(tmp_path, items_file, monkeypatch):
    slept = []
    monkeypatch.setattr(gb, "_sleep", slept.append)
    _fake_decide(monkeypatch, _choice("c1"))
    _run(tmp_path, items_file, "jev", "--stage", "verify", "--delay", "2")
    assert slept == [2.0]  # two sent calls, one gap; the no-call control is local


def test_progress_goes_to_stderr_every_25_items_and_never_shows_content(tmp_path, monkeypatch, capsys):
    _fake_local(monkeypatch, '{"canonical": "SECRET-ANSWER", "confidence": "high"}')
    _run(tmp_path, _many(tmp_path, 30), "qwen-local")
    err = capsys.readouterr().err
    assert err.count("25/30") == 1 and "SECRET-ANSWER" not in err and "adjudicat" not in err.lower()


def test_the_startup_line_names_exactly_the_fields_sent_to_a_third_party(tmp_path, items_file, monkeypatch, capsys):
    _fake_decide(monkeypatch, _choice("c1"))
    _run(tmp_path, items_file, "mercury-decide", "--stage", "verify")
    first = capsys.readouterr().out.splitlines()[0]
    assert "mercury-decide" in first and "show title" in first and "mined term" in first and "wiki candidate titles" in first
    assert "transcript" not in first  # verify only
    _fake_local(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
    _run(tmp_path, items_file, "qwen-local", "--stage", "verify", out="local.jsonl")
    assert "stays on this machine" in capsys.readouterr().out.splitlines()[0]


def test_the_startup_line_mentions_quotes_when_acquire_can_send_them(tmp_path, items_file, monkeypatch, capsys):
    _fake_openai(monkeypatch, '{"same_entity": true, "confidence": "high"}')
    _run(tmp_path, items_file, "longcat-2.0", "--stage", "acquire")
    assert "transcript quotes" in capsys.readouterr().out.splitlines()[0]


def test_a_third_party_arm_without_its_key_exits_naming_only_the_variable(tmp_path, items_file, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_JEV_API_KEY")
    with pytest.raises(SystemExit) as e:
        _run(tmp_path, items_file, "jev")
    assert e.value.code == 2 and "OPENROUTER_JEV_API_KEY" in capsys.readouterr().err


def test_bad_arguments_exit_2(tmp_path, items_file):
    for argv in (
        ["run", "--items", str(items_file), "--arm", "nope", "--out", str(tmp_path / "o")],
        ["run", "--items", str(tmp_path / "missing.jsonl"), "--arm", "jev", "--out", str(tmp_path / "o")],
        ["run", "--items", str(items_file), "--arm", "jev", "--out", str(tmp_path / "o"), "--only", "some"],
        ["run", "--items", str(items_file), "--arm", "jev", "--out", str(tmp_path / "o"), "--delay", "-1"],
    ):
        with pytest.raises(SystemExit) as e:
            gb.main(argv)
        assert e.value.code == 2, argv


def test_no_key_value_is_ever_written_to_the_results_file(tmp_path, items_file, monkeypatch, capsys):
    _fake_decide(monkeypatch, _choice("c1"))
    _, _, outp = _run(tmp_path, items_file, "jev")
    out = capsys.readouterr()
    assert KEY not in outp.read_text(encoding="utf-8") + out.out + out.err
