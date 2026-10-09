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
import tools.glossary_score as glossary_score  # noqa: E402

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
    monkeypatch.setenv("COMMANDCODE_API_KEY", KEY)


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
    assert {r[n].key_env for n in r if r[n].kind == "decision" and n != "jev"} == {"OPENROUTER_JEV_API_KEY"}
    assert all(r[n].model in dc.ALLOWED_MODELS for n in r if r[n].kind == "decision" and n != "jev")
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
    def fake(
        url, model, prompt, key_env, extra_body=None, usage_sink=None, max_tokens=1024, delay=0.0, first_line=True, deadline=None
    ):
        if seen is not None:
            seen.append(
                {
                    "url": url, "model": model, "prompt": prompt, "key_env": key_env, "extra": extra_body,
                    "first_line": first_line, "deadline": deadline,
                }
            )  # fmt: skip
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
        return {next(iter(questions)): {"type": "noul", "noul": scores[title]}}

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
    assert "goes only to the production llm_chat endpoint" in capsys.readouterr().out.splitlines()[0]


def test_the_startup_line_mentions_quotes_when_acquire_can_send_them(tmp_path, items_file, monkeypatch, capsys):
    _fake_openai(monkeypatch, '{"same_entity": true, "confidence": "high"}')
    _run(tmp_path, items_file, "longcat-2.0", "--stage", "acquire")
    assert "transcript quotes" in capsys.readouterr().out.splitlines()[0]


def test_a_third_party_arm_without_its_key_exits_naming_only_the_variable(tmp_path, items_file, monkeypatch, capsys):
    monkeypatch.delenv("COMMANDCODE_API_KEY")
    with pytest.raises(SystemExit) as e:
        _run(tmp_path, items_file, "jev")
    err = capsys.readouterr().err
    assert e.value.code == 2 and "COMMANDCODE_API_KEY" in err
    assert "OPENROUTER" not in err  # no OpenRouter fallback for jev


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


# =====================================================================================
# Phase 1b: honest gold labels, synthetic negatives, honest framing
# =====================================================================================

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _one_show(tmp_path, gloss, titles, name="Case Show", fetched_at=1, api="https://x/api.php"):
    g, w = tmp_path / "g", tmp_path / "w"
    _put(g / f"{name}.json", {"show": name, **gloss})
    _put(w / (re.sub(r"[^A-Za-z0-9]+", "_", name) + ".json"), {"api": api, "fetched_at": fetched_at, "titles": titles})
    return g, w


def _items_for(tmp_path, gloss, titles, **kw):
    g, w = _one_show(tmp_path, gloss, titles, **kw)
    return _build(tmp_path, g, w)[1]


def _by_term(items, term, stage="verify"):
    return next(i for i in items if i["stage"] == stage and i.get("term") == term and not i.get("negative"))


def test_a_curated_respelling_or_other_character_is_never_gold(tmp_path):
    """The reviewer's reproduction: another character with similar letters became the 'right answer'."""
    gloss = {"_curated": True, "names": ["Nanami", "Hanami", "Grandpa", "Panda"], "phrases": []}
    items = _items_for(tmp_path, gloss, ["Hanami", "Panda", "Kento Nanami"])
    nanami = _by_term(items, "Nanami")
    assert "Hanami" in [c["title"] for c in nanami["candidates"]]  # the trap is really in the candidate list
    assert nanami["gold"] != "Hanami" and nanami["gold"] is None  # Kento Nanami is not a curated name here
    assert _by_term(items, "Grandpa")["gold"] != "Panda"


def test_an_expansion_that_is_a_curated_name_is_gold(tmp_path):
    gloss = {"_curated": True, "names": ["Nanami", "Hanami", "Kento Nanami"], "phrases": []}
    nanami = _by_term(_items_for(tmp_path, gloss, ["Hanami", "Kento Nanami"]), "Nanami")
    assert nanami["gold"] == "Kento Nanami" and nanami["gold_kind"] == "expansion" and nanami["gold_source"] == "curated"


def test_an_exact_match_is_gold_kind_exact(tmp_path):
    gloss = {"_curated": True, "names": ["Zoro"], "phrases": []}
    zoro = _by_term(_items_for(tmp_path, gloss, ["Zoro", "Zorro Jr"]), "Zoro")
    assert zoro["gold"] == "Zoro" and zoro["gold_kind"] == "exact" and zoro["incumbent_derived"] is False


def test_two_qualifying_candidates_mean_no_gold_and_no_tie_break(tmp_path):
    gloss = {"_curated": True, "names": ["Nanami", "Kento Nanami", "Nana Nanami"], "phrases": []}
    nanami = _by_term(_items_for(tmp_path, gloss, ["Kento Nanami", "Nana Nanami"]), "Nanami")
    assert len(nanami["candidates"]) == 2
    assert (
        nanami["gold"] is None and nanami["gold_ambiguous"] is True and "gold_kind" not in nanami and "gold_accept" not in nanami
    )


def test_an_exact_title_plus_a_whole_word_expansion_gives_gold_with_an_accept_set(tmp_path):
    """These used to be null-ambiguous although BOTH answers are right (production would add the expansion)."""
    gloss = {"_curated": True, "names": ["Nanami", "Kento Nanami"], "phrases": []}
    nanami = _by_term(_items_for(tmp_path, gloss, ["Nanami", "Kento Nanami"]), "Nanami")
    assert nanami["gold"] == "Nanami" and nanami["gold_kind"] == "exact" and "gold_ambiguous" not in nanami
    assert nanami["gold_accept"] == ["Nanami", "Kento Nanami"]


def test_gold_accept_is_the_exact_title_plus_whole_word_expansions_only(tmp_path):
    gloss = {"_curated": True, "names": ["Luffy"], "phrases": []}  # the expansion need not be curated for the accept set
    luffy = _by_term(_items_for(tmp_path, gloss, ["Luffy", "Lord Luffy", "Luffyx"]), "Luffy")
    assert luffy["gold"] == "Luffy" and luffy["gold_accept"] == ["Luffy", "Lord Luffy"]  # "Luffyx" is mid-word


def test_an_expansion_gold_accepts_just_itself(tmp_path):
    gloss = {"_curated": True, "names": ["Doflamingo", "Donquixote Doflamingo"], "phrases": []}
    d = _by_term(_items_for(tmp_path, gloss, ["Donquixote Doflamingo"]), "Doflamingo")
    assert (
        d["gold"] == "Donquixote Doflamingo" and d["gold_kind"] == "expansion" and d["gold_accept"] == ["Donquixote Doflamingo"]
    )


def test_a_surname_shared_with_another_wiki_title_is_ambiguous_not_gold(tmp_path):
    """The reviewer's family case: the curated member is only one of several people who carry the surname."""
    gloss = {"_curated": True, "names": ["Nanami", "Kento Nanami"], "phrases": []}
    titles = ["Kento Nanami", "Nanako Nanami", "Unrelated Page"]  # the protagonist's sister is on the wiki too
    items = _items_for(tmp_path, gloss, titles)
    nanami = _by_term(items, "Nanami")
    assert "Kento Nanami" in [c["title"] for c in nanami["candidates"]]
    assert nanami["gold"] is None and nanami["gold_ambiguous"] is True


def test_a_title_outside_the_candidates_still_counts_for_the_family_check(tmp_path):
    """The whole wiki list is checked, not just the six candidates."""
    gloss = {"_curated": True, "names": ["Nanami", "Kento Nanami"], "phrases": []}
    titles = ["Kento Nanami", "Nanami Is My Cousin And Also A Very Long Page Title Indeed"]
    nanami = _by_term(_items_for(tmp_path, gloss, titles), "Nanami")
    assert [c["title"] for c in nanami["candidates"]] == ["Kento Nanami"] and nanami["gold"] is None and nanami["gold_ambiguous"]


def test_a_mid_word_or_ratio_only_expansion_is_not_gold(tmp_path, monkeypatch):
    gloss = {"_curated": True, "names": ["Nami", "Namie"], "phrases": []}
    nami = _by_term(_items_for(tmp_path, gloss, ["Namie"]), "Nami")
    assert [c["title"] for c in nami["candidates"]] == ["Namie"] and nami["gold"] is None  # substring, not a whole word
    monkeypatch.setattr(gb.glossary_acquire, "is_expansion", lambda a, b: True)  # a ratio-only pass: the term is not in the title
    assert gb._gold("Nami", ["Lonely Harbour"], {"_curated": True, "names": ["Nami", "Lonely Harbour"]}, ["Lonely Harbour"]) == (
        None, None, False, [],
    )  # fmt: skip


def test_a_whole_word_suffix_and_prefix_are_accepted(tmp_path):
    suffix = {"_curated": True, "names": ["Doflamingo", "Donquixote Doflamingo"], "phrases": []}
    assert _by_term(_items_for(tmp_path, suffix, ["Donquixote Doflamingo"]), "Doflamingo")["gold_kind"] == "expansion"
    (tmp_path / "p").mkdir()
    prefix = {"_curated": True, "names": ["Kento", "Kento San"], "phrases": []}
    assert _by_term(_items_for(tmp_path / "p", prefix, ["Kento San"]), "Kento")["gold"] == "Kento San"


def test_hard_fixes_targets_are_not_a_gold_source(tmp_path):
    gloss = {"_curated": True, "names": ["Zoro"], "phrases": [], "hard_fixes": {"zorro": "Roronoa Zoro"}}
    zoro = _by_term(_items_for(tmp_path, gloss, ["Roronoa Zoro"]), "Zoro")
    assert zoro["gold"] is None


def test_an_expansion_gold_of_a_verified_term_is_flagged_incumbent_derived(tmp_path):
    gloss = {"_curated": True, "names": ["Nanami", "Kento Nanami"], "phrases": [], "verified": ["Nanami"]}
    items = _items_for(tmp_path, gloss, ["Kento Nanami"])
    assert _by_term(items, "Nanami")["incumbent_derived"] is True
    gloss["verified"] = []
    (tmp_path / "second").mkdir()
    items = _items_for(tmp_path / "second", gloss, ["Kento Nanami"])
    assert _by_term(items, "Nanami")["incumbent_derived"] is False


def _neg_fixture(tmp_path):
    gloss = {"_curated": True, "names": ["Nami", "Luffy", "Solo"], "phrases": []}
    titles = ["Nami", "Naomi", "Namie", "Luffy", "Monkey D. Luffy", "Solo"]
    return _items_for(tmp_path, gloss, titles)


def test_negatives_come_only_from_exact_gold_and_drop_the_title_and_every_expansion(tmp_path):
    items = _neg_fixture(tmp_path)
    nami = _by_term(items, "Nami")
    assert nami["gold_kind"] == "exact" and [c["title"] for c in nami["candidates"]][0] == "Nami"
    neg = next(i for i in items if i["id"] == "verify-neg:Case Show:Nami")
    assert neg["negative"] is True and neg["source_id"] == nami["id"] and neg["gold"] == "none" and neg["stage"] == "verify"
    titles = [c["title"] for c in neg["candidates"]]
    assert "Nami" not in titles and "Namie" not in titles  # the exact title and an expansion are gone
    assert titles == [c["title"] for c in nami["candidates"] if c["title"] in titles]  # production order kept
    by_title = {c["title"]: c["score"] for c in nami["candidates"]}
    assert all(c["score"] == by_title[c["title"]] for c in neg["candidates"])  # scores untouched
    assert titles == ["Naomi"] and neg["no_call"] is False


def test_a_negative_whose_candidates_all_disappear_is_skipped(tmp_path):
    items = _neg_fixture(tmp_path)
    assert not [
        i for i in items if i["id"] in ("verify-neg:Case Show:Luffy", "verify-neg:Case Show:Solo")
    ]  # only expansions / nothing left


def test_negatives_are_not_made_from_expansion_gold_and_ids_are_unique(tmp_path):
    gloss = {"_curated": True, "names": ["Nanami", "Hanami", "Kento Nanami"], "phrases": []}
    items = _items_for(tmp_path, gloss, ["Hanami", "Kento Nanami"])
    assert not [i for i in items if i.get("negative") and i["term"] == "Nanami"]
    (tmp_path / "again").mkdir()
    ids = [i["id"] for i in _neg_fixture(tmp_path / "again")]
    assert len(ids) == len(set(ids))


def test_existing_item_ids_and_candidates_are_what_phase_1_produced(tmp_path, data):
    """The baseline run joins on these: ids and candidate lists/order must not move."""
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    ids = {i["id"] for i in items}
    for term in ("Zoro", "Luffy", "Nami", "Sanji", "Chopper", "Straw Hat Pirates"):
        assert f"verify:Alpha Show:{term}" in ids
    assert "verify:Beta Show:Kaido" in ids and "acquire:Alpha Show:Zoroo|Zoro" in ids
    for it in (i for i in items if i["stage"] == "verify" and not i.get("negative") and i["show"] == "Alpha Show"):
        assert [c["title"] for c in it["candidates"]] == gv.candidates(it["term"], ALPHA_TITLES)


def test_would_ask_matches_what_production_verify_would_actually_adjudicate(tmp_path, monkeypatch):
    gloss = {"names": ["Kaido", "Zoro", "Luffy"], "phrases": [], "verified": ["Zoro"]}
    g, w = _one_show(tmp_path, gloss, ["Kaido", "Luffy", "Zoro"], name="Parity Show")
    items = _build(tmp_path, g, w)[1]
    asked = []
    monkeypatch.setattr(gv, "resolve_wiki", lambda title, override=None: "https://x/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Kaido", "Luffy", "Zoro"])
    monkeypatch.setattr(
        gv, "adjudicate", lambda term, cands, show: asked.append(term) or {"canonical": "", "confidence": "none", "dub_note": ""}
    )
    gv.verify(str(g / "Parity Show.json"))
    assert sorted(asked) == sorted(i["term"] for i in items if i["would_ask"])
    assert [i["would_ask"] for i in items if i["term"] == "Zoro"] == [False]


def test_would_ask_is_false_for_a_show_production_refuses_as_a_wiki_mismatch(tmp_path, monkeypatch):
    gloss = {"names": ["Aaa", "Bbb", "Ccc"], "phrases": []}  # none of these is a wiki title, no pinned wiki
    g, w = _one_show(tmp_path, gloss, ["Totally Different", "Other Page"], name="Mismatch Show")
    items = _build(tmp_path, g, w)[1]
    assert items and not any(i["would_ask"] for i in items)
    monkeypatch.setattr(gv, "resolve_wiki", lambda title, override=None: "https://x/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Totally Different", "Other Page"])
    monkeypatch.setattr(gv, "adjudicate", lambda *a: pytest.fail("production refuses this show before any call"))
    assert "mismatch" in gv.verify(str(g / "Mismatch Show.json"))["note"]
    gloss["wiki"] = "https://pinned.example/api.php"  # a pinned wiki skips the gate
    g2, w2 = _one_show(tmp_path / "p", gloss, ["Totally Different"], name="Mismatch Show")
    assert all(i["would_ask"] for i in _build(tmp_path / "p", g2, w2)[1])


def test_wiki_cache_staleness_follows_the_production_refresh_rule(tmp_path):
    day = 24 * 3600
    ttl = gv.WIKI_TTL
    g, w = _one_show(tmp_path, {"names": ["Kaido"], "phrases": []}, ["Kaido"], name="Old Show", fetched_at=1000)
    _put(w / "Fresh_Show.json", {"api": "https://x/api.php", "fetched_at": 1000 + ttl + day, "titles": ["T"]})
    items = _build(tmp_path, g, w)[1]
    assert items[0]["wiki_cache_stale"] is True  # older than WIKI_TTL as of the freshest cache in the snapshot
    code, items2, _ = _build(tmp_path, g, w, "--as-of", str(1000 + ttl - 1), name="b.jsonl")
    assert items2[0]["wiki_cache_stale"] is False


def test_a_pinned_wiki_that_differs_from_the_cached_api_is_stale(tmp_path):
    gloss = {"names": ["Kaido"], "phrases": [], "wiki": "https://other.example/wiki/Main"}
    items = _items_for(tmp_path, gloss, ["Kaido"], fetched_at=10**10, api="https://x/api.php")
    assert items[0]["wiki_cache_stale"] is True  # fetch_titles would refetch: the api differs


def test_the_summary_is_honest_about_what_the_set_is(tmp_path, data, capsys):
    g, w = data
    _build(tmp_path, g, w)
    out = capsys.readouterr().out
    assert "verify --force" in out and "offline snapshot" in out
    for label in ("exact", "expansion", "incumbent-derived", "ambiguous", "single-candidate", "negatives", "would_ask"):
        assert label in out
    assert "items production would ask" not in out


def test_the_set_is_identical_across_processes_with_different_hash_seeds(tmp_path, data):
    g, w = data
    outs = []
    for seed in ("1", "2"):
        out = tmp_path / f"seed{seed}.jsonl"
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run(
            [sys.executable, "tools/glossary_bakeoff.py", "build-set", "--glossaries", str(g)]
            + ["--wiki-cache", str(w), "--out", str(out)],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=120, check=False,
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        outs.append(out.read_bytes())
    assert outs[0] == outs[1] and outs[0]


def test_an_unwritable_out_is_a_clean_message_and_exit_1(tmp_path, data, capsys):
    g, w = data
    code = gb.main(
        ["build-set", "--glossaries", str(g), "--wiki-cache", str(w), "--out", str(tmp_path / "no" / "such" / "dir" / "o.jsonl")]
    )
    err = capsys.readouterr().err
    assert code == 1 and "--out" in err and "Traceback" not in err


def test_a_malformed_glossary_says_its_acquire_cache_was_not_read(tmp_path, capsys):
    g, w = tmp_path / "g", tmp_path / "w"
    _put(g / "Broken Show.json", "{ nope")
    _put(g / "Broken Show.acquire-cache.json", {"A": {"B": {"same_entity": True, "confidence": "high"}}})
    w.mkdir()
    code, items, _ = _build(tmp_path, g, w)
    out = capsys.readouterr().out
    assert code == 0 and not items and "Broken Show" in out and "acquire cache" in out and "not read" in out


def test_the_registry_pins_the_verified_endpoints_models_and_pacing():
    r = gb.ARMS
    nemo, lc20, lc25 = r["nemotron-super"], r["longcat-2.0"], r["longcat-2.5"]
    assert (
        nemo.url == "https://integrate.api.nvidia.com/v1/chat/completions" and nemo.model == "nvidia/nemotron-3-super-120b-a12b"
    )
    assert nemo.key_env == "NVIDIA_API_KEY" and nemo.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    for lc, model in ((lc20, "LongCat-2.0"), (lc25, "LongCat-2.5-Preview")):
        assert lc.url == "https://api.longcat.chat/openai/v1/chat/completions" and lc.model == model
        assert lc.key_env == "LONGCATAI_API_KEY" and lc.extra_body == {"thinking": {"type": "disabled"}}
    assert nemo.delay >= 1.6  # NVIDIA's free tier is ~40 requests a minute
    assert lc20.delay == lc25.delay == 0.3


def test_an_arms_default_delay_applies_unless_delay_is_given(tmp_path, items_file, monkeypatch):
    slept = []
    monkeypatch.setattr(gb, "_sleep", slept.append)
    _fake_openai(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
    _run(tmp_path, items_file, "nemotron-super", "--stage", "verify")
    assert slept == [gb.ARMS["nemotron-super"].delay]
    slept.clear()
    _run(tmp_path, items_file, "nemotron-super", "--stage", "verify", "--delay", "0", out="b.jsonl")
    assert slept == []  # an explicit --delay 0 wins over the arm's default


# =====================================================================================
# Phase 2b: the reviewer's findings on `run`
# =====================================================================================


def _decision_answer_with(**extra):
    return {"pick": {"type": "choice", "choice": "c1", "probabilities": {"c1": 1.0}, "confidence": 0.9, **extra}}


def test_a_429_storm_stops_the_run_after_five_consecutive_rate_limits(tmp_path, monkeypatch, capsys):
    attempts = []

    def always_429(*a, **k):
        attempts.append(1)
        raise dc.DecisionHTTPError(429)

    monkeypatch.setattr(dc, "decide", always_429)
    code, rows, _ = _run(tmp_path, _many(tmp_path, 20), "jev")
    assert code == 3 and len(rows) == 5 and len(attempts) == 5
    assert "rate limited, resume later with --retry-errors" in capsys.readouterr().err


def test_a_429_streak_is_broken_by_any_answer(tmp_path, monkeypatch):
    n = []

    def flaky(*a, **k):
        n.append(1)
        if len(n) % 5 == 0:
            return dc.DecisionResult(answers=_decision_answer_with(), usage={}, latency_s=0.1, model="typesafe/jev-1.13")
        raise dc.DecisionHTTPError(429)

    monkeypatch.setattr(dc, "decide", flaky)
    code, rows, _ = _run(tmp_path, _many(tmp_path, 12), "jev")
    assert code == 0 and len(rows) == 12  # never 5 in a row


def test_a_text_arm_rate_limit_counts_too(tmp_path, monkeypatch):
    _fake_openai(monkeypatch, "<ERROR rate-limited (HTTP 429)>")
    code, rows, _ = _run(tmp_path, _many(tmp_path, 20), "nemotron-super")
    assert code == 3 and len(rows) == 5


def test_five_consecutive_server_errors_trip_the_breaker_with_its_own_message(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise dc.DecisionHTTPError(503)

    monkeypatch.setattr(dc, "decide", boom)
    code, rows, _ = _run(tmp_path, _many(tmp_path, 12), "jev")
    assert code == 3 and len(rows) == 5
    err = capsys.readouterr().err
    assert "provider failing, resume later with --retry-errors" in err and "rate limited" not in err


@pytest.mark.parametrize("exc", [TimeoutError, OSError, ValueError])
def test_five_consecutive_transport_errors_trip_it_too(tmp_path, monkeypatch, exc):
    monkeypatch.setattr(dc, "decide", lambda *a, **k: (_ for _ in ()).throw(exc("x")))
    code, rows, _ = _run(tmp_path, _many(tmp_path, 12), "jev")
    assert code == 3 and len(rows) == 5


def test_four_errors_then_an_answer_do_not_trip_it(tmp_path, monkeypatch):
    n = []

    def flaky(*a, **k):
        n.append(1)
        if len(n) % 5 == 0:
            return dc.DecisionResult(answers=_decision_answer_with(), usage={}, latency_s=0.1, model="typesafe/jev")
        raise dc.DecisionHTTPError(500)

    monkeypatch.setattr(dc, "decide", flaky)
    code, rows, _ = _run(tmp_path, _many(tmp_path, 12), "jev")
    assert code == 0 and len(rows) == 12


def test_a_resume_after_a_breaker_stop_works_with_retry_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "decide", lambda *a, **k: (_ for _ in ()).throw(dc.DecisionHTTPError(429)))
    many = _many(tmp_path, 8)
    _run(tmp_path, many, "jev")
    monkeypatch.setattr(dc, "decide", lambda *a, **k: dc.DecisionResult(_decision_answer_with(), {}, 0.1, "typesafe/jev-1.13"))
    code, rows, _ = _run(tmp_path, many, "jev", "--retry-errors")
    assert code == 0
    latest = {}
    for r in rows:
        latest[r["id"]] = r
    assert len(latest) == 8 and not any(r["error"] for r in latest.values())


def test_only_whitelisted_answer_fields_are_stored(tmp_path, items_file, monkeypatch):
    secret_header = f"Authorization: Bearer {KEY}"
    _fake_decide(monkeypatch, lambda m, s, q: _decision_answer_with(debug=secret_header, trace={"echo": secret_header}))
    _, rows, outp = _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    assert set(rows[0]["raw"]["answer"]) == {"type", "choice", "probabilities", "confidence"}
    assert KEY not in outp.read_text(encoding="utf-8")


def test_whitelisting_also_covers_span_and_noul_answers(tmp_path, items_file, monkeypatch):
    leaky = {"type": "noul", "noul": 0.4, "debug": f"Bearer {KEY}"}
    _fake_decide(monkeypatch, lambda m, s, q: {next(iter(q)): leaky})
    _, rows, outp = _run(tmp_path, items_file, "span-01-lite", "--stage", "verify", "--only", "gold")
    assert rows[0]["raw"][0]["answer"] == {"type": "noul", "noul": 0.4} and KEY not in outp.read_text(encoding="utf-8")
    _, rows, outp = _run(tmp_path, items_file, "jev", "--stage", "acquire", out="acq.jsonl")
    assert KEY not in outp.read_text(encoding="utf-8")


def test_the_arms_key_value_is_redacted_from_any_row_before_it_is_written(tmp_path, items_file, monkeypatch):
    """Defence in depth: even a text arm whose reply echoes the key cannot put it in the results file."""
    _fake_openai(monkeypatch, f'{{"canonical": "{KEY}", "confidence": "high"}}')
    _, rows, outp = _run(tmp_path, items_file, "longcat-2.0", "--stage", "verify", "--only", "gold")
    text = outp.read_text(encoding="utf-8")
    assert KEY not in text and "***" in text and rows[0]["parsed"]["canonical"] == "***"


def test_latest_row_per_key_wins(tmp_path, items_file, monkeypatch):
    """GUARD: passes on the old code; the reviewer's mutation (first row wins) used to pass the suite."""
    calls = _fake_local(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
    outp = tmp_path / "res" / "out.jsonl"
    outp.parent.mkdir()
    base = {"arm": "qwen-local", "order": "fwd"}
    zoro, luffy = "verify:Alpha Show:Zoro", "verify:Alpha Show:Luffy"
    rows = [
        {**base, "id": zoro, "error": "boom", "parsed": None},  # an error, then...
        {**base, "id": zoro, "error": None, "parsed": {"canonical": "Zoro", "confidence": "high"}},  # ...a good row: done
        {**base, "id": luffy, "error": None, "parsed": {"canonical": "Luffy", "confidence": "high"}},  # a good row, then...
        {**base, "id": luffy, "error": "boom", "parsed": None},  # ...an error: the error wins
    ]
    outp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    _run(tmp_path, items_file, "qwen-local", "--stage", "verify", "--only", "all")
    assert calls == []  # both keys are settled: the first is done, the second is an error that is not retried by default
    _run(tmp_path, items_file, "qwen-local", "--stage", "verify", "--retry-errors")
    assert len(calls) == 1 and "Luffy" in calls[0][0]  # only the key whose latest row is an error


def test_the_span_branch_follows_the_effective_model_not_the_registry_default(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_decide(monkeypatch, lambda m, s, q: {next(iter(q)): {"type": "noul", "noul": 0.5}}, seen)
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_MODEL", "respan/span-01-lite")
    _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    assert seen and all(next(iter(s["questions"].values()))["type"] == "noul" for s in seen)
    assert {s["model"] for s in seen} == {"respan/span-01-lite"}


def test_the_local_arms_startup_line_names_the_endpoint_not_a_promise_of_locality(tmp_path, items_file, monkeypatch, capsys):
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "VERIFY_LLAMACPP_URL", "http://10.1.2.3:8090/v1/chat/completions")
    _fake_local(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
    _run(tmp_path, items_file, "qwen-local", "--stage", "verify")
    first = capsys.readouterr().out.splitlines()[0]
    assert "goes only to the production llm_chat endpoint (10.1.2.3:8090)" in first and "nothing leaves" not in first


def test_text_arms_get_a_total_request_deadline_from_the_harness(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_openai(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}', seen)
    _run(tmp_path, items_file, "longcat-2.0", "--stage", "verify")
    assert seen[0]["deadline"] == gb.repair._request_deadline() and seen[0]["deadline"] >= 10


def test_out_equal_to_items_is_refused(tmp_path, items_file, capsys):
    before = items_file.read_bytes()
    link = tmp_path / "alias.jsonl"
    link.symlink_to(items_file)
    for target in (items_file, link):
        with pytest.raises(SystemExit) as e:
            gb.main(["run", "--items", str(items_file), "--arm", "qwen-local", "--out", str(target)])
        assert e.value.code == 2 and "--out" in capsys.readouterr().err
    assert items_file.read_bytes() == before


def test_decision_rows_record_the_served_model_id(tmp_path, items_file, monkeypatch):
    monkeypatch.setattr(
        dc, "decide", lambda *a, **k: dc.DecisionResult(_decision_answer_with(), {}, 0.1, "typesafe/jev-1.13-20260917")
    )
    _, rows, _ = _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    assert rows[0]["served_model"] == "typesafe/jev-1.13-20260917"


# --- jev now runs on CommandCode's Provider API --------------------------------------------------------------

import http.server  # noqa: E402
import threading  # noqa: E402


class _FakeCCForRun:
    def __init__(self, status=200, body=None):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(self.rfile.read(length))}
                )
                ok = {
                    "model": "typesafe/jev",
                    "answers": _decision_answer_with(),
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                }
                payload = json.dumps(body if body is not None else ok).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/provider/v1/systemone"

    def close(self):
        self.srv.shutdown()


def test_the_jev_arm_is_commandcode_with_no_openrouter_fallback():
    jev = gb.ARMS["jev"]
    assert jev.url == "https://api.commandcode.ai/provider/v1/systemone" and jev.model == "typesafe/jev"
    assert jev.key_env == "COMMANDCODE_API_KEY" and jev.provider == "commandcode" and jev.kind == "decision"
    assert all(gb.ARMS[n].provider == "openrouter" for n in gb.ARMS if gb.ARMS[n].kind == "decision" and n != "jev")
    assert jev.model in dc.COMMANDCODE_MODELS and jev.model not in dc.ALLOWED_MODELS


def test_jev_passes_its_provider_and_key_env_to_the_client(tmp_path, items_file, monkeypatch):
    seen = []

    def fake(model, state, questions, key_env, **kw):
        seen.append({"model": model, "key_env": key_env, **kw})
        return dc.DecisionResult(answers=_decision_answer_with(), usage={}, latency_s=0.1, model="typesafe/jev")

    monkeypatch.setattr(dc, "decide", fake)
    _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    assert seen[0]["model"] == "typesafe/jev" and seen[0]["key_env"] == "COMMANDCODE_API_KEY"
    assert seen[0]["provider"] == "commandcode" and seen[0]["url"] == "https://api.commandcode.ai/provider/v1/systemone"
    seen.clear()
    _run(tmp_path, items_file, "mercury-decide", "--stage", "verify", "--only", "gold", out="m.jsonl")
    assert seen[0]["provider"] == "openrouter" and seen[0]["key_env"] == "OPENROUTER_JEV_API_KEY"


def test_the_startup_line_names_the_commandcode_host_for_jev(tmp_path, items_file, monkeypatch, capsys):
    _fake_decide(monkeypatch, _decision_answer_with())
    _run(tmp_path, items_file, "jev", "--stage", "verify")
    first = capsys.readouterr().out.splitlines()[0]
    assert "sends to api.commandcode.ai" in first and "openrouter" not in first


def test_jev_end_to_end_against_a_fake_commandcode_server(tmp_path, items_file, monkeypatch):
    cc = _FakeCCForRun()
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_URL", cc.url)
    try:
        _, rows, outp = _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    finally:
        cc.close()
    r = cc.requests[0]
    assert r["path"] == "/provider/v1/systemone" and r["auth"] == f"Bearer {KEY}" and r["body"]["model"] == "typesafe/jev"
    assert rows[0]["parsed"]["choice"] == "c1" and rows[0]["served_model"] == "typesafe/jev"
    assert KEY not in outp.read_text(encoding="utf-8")


def test_a_commandcode_quota_429_trips_the_same_breaker_without_leaking_the_key(tmp_path, items_file, monkeypatch, capsys):
    cc = _FakeCCForRun(status=429, body={"error": f"daily request cap reached ({KEY})"})
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_URL", cc.url)
    monkeypatch.setattr(dc.time, "sleep", lambda s: None)
    try:
        code, rows, outp = _run(tmp_path, _many(tmp_path, 20), "jev")
    finally:
        cc.close()
    err = capsys.readouterr()
    assert code == 3 and len(rows) == 5 and "rate limited, resume later with --retry-errors" in err.err
    assert all(r["error"] == "HTTP 429" for r in rows)
    assert KEY not in outp.read_text(encoding="utf-8") + err.out + err.err


# --- round 2d: provider hosts through the override, request estimate, redaction forms ---------------------------------


def test_a_url_override_cannot_send_one_providers_key_to_the_others_host(tmp_path, items_file, monkeypatch):
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_URL", "https://openrouter.ai/api/alpha/decisions")
    sent = []
    monkeypatch.setattr(dc.repair, "_post_json", lambda *a, **k: sent.append(a) or {})
    _, rows, _ = _run(tmp_path, items_file, "jev", "--stage", "verify", "--only", "gold")
    assert not sent and rows[0]["error"] and "host" in rows[0]["error"] and rows[0]["parsed"] is None


def test_the_request_estimate_is_printed_before_the_first_call(tmp_path, items_file, monkeypatch, capsys):
    order = []
    monkeypatch.setattr(
        dc, "decide", lambda *a, **k: order.append("call") or dc.DecisionResult(_decision_answer_with(), {}, 0.1, "typesafe/jev")
    )
    monkeypatch.setattr(gb, "_sleep", lambda s: None)
    real_print = print

    def spy(*a, **k):
        order.append("print:" + " ".join(str(x) for x in a)[:40])
        real_print(*a, **k)

    monkeypatch.setattr("builtins.print", spy)
    _run(tmp_path, items_file, "jev", "--stage", "verify")
    lines = [o for o in order if o.startswith("print:run: request estimate")]
    assert lines and order.index(lines[0]) < order.index("call")


def test_the_request_estimate_counts_worst_case_requests_per_arm_kind(tmp_path, items_file, monkeypatch, capsys):
    # items_file verify items: Zoro (2 candidates), Luffy (2), qqq (a no-call control: never sent)
    def estimate(arm, *extra):
        _fake_decide(monkeypatch, _decision_answer_with())
        _fake_openai(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
        _fake_local(monkeypatch, '{"canonical": "Zoro", "confidence": "high"}')
        _run(tmp_path, items_file, arm, "--stage", "verify", *extra, out=f"{arm}-{len(extra)}.jsonl")
        out = capsys.readouterr().out
        return next(line for line in out.splitlines() if line.startswith("run: request estimate"))

    assert "at most 6 request(s)" in estimate("jev")  # 2 sendable items x 3 (one try + 2 retries)
    assert "at most 4 request(s)" in estimate("longcat-2.0")  # 2 x 2 (one try + one retry)
    assert "at most 12 request(s)" in estimate("span-01-lite")  # 2 items x (2 candidates x 3)
    assert "no third-party requests" in estimate("qwen-local")


def test_the_estimate_ignores_rows_already_done(tmp_path, items_file, monkeypatch, capsys):
    _fake_decide(monkeypatch, _decision_answer_with())
    monkeypatch.setattr(dc, "decide", lambda *a, **k: dc.DecisionResult(_decision_answer_with(), {}, 0.1, "typesafe/jev"))
    _run(tmp_path, items_file, "jev", "--stage", "verify")
    capsys.readouterr()
    _run(tmp_path, items_file, "jev", "--stage", "verify")
    assert "at most 0 request(s)" in capsys.readouterr().out


def test_span_estimates_are_capped_at_eighteen_per_item(tmp_path, monkeypatch, capsys):
    p = tmp_path / "wide.jsonl"
    p.write_text(json.dumps(_vitem("Wide", [f"T{i}" for i in range(6)])) + "\n", encoding="utf-8")
    _fake_decide(monkeypatch, _decision_answer_with())
    _run(tmp_path, p, "span-01-lite")
    assert "at most 18 request(s)" in capsys.readouterr().out


def test_the_keys_json_escaped_and_url_encoded_forms_are_redacted_too(tmp_path, items_file, monkeypatch):
    import urllib.parse

    tricky = 'sk-a"b\\c+d/e=f'
    monkeypatch.setenv("LONGCATAI_API_KEY", tricky)
    reply = json.dumps(
        {"canonical": f"{urllib.parse.quote(tricky, safe='')} and {urllib.parse.quote_plus(tricky)}", "confidence": "high"}
    )
    _fake_openai(monkeypatch, reply)
    _, rows, outp = _run(tmp_path, items_file, "longcat-2.0", "--stage", "verify", "--only", "gold")
    text = outp.read_text(encoding="utf-8")
    forms = [tricky, json.dumps(tricky)[1:-1], urllib.parse.quote(tricky, safe=""), urllib.parse.quote_plus(tricky)]
    for form in forms:
        assert form not in text, form
    assert "***" in text


# --- the live noul shape through the harness (fake servers return the captured shape) ----------------------------------

SPAN_SERVED = "respan/span-01-lite-20260925"


class _NoulServer:
    """127.0.0.1 stand-in for a decisions endpoint: answers every question with the captured noul shape."""

    def __init__(self, noul_for, served, leak=False):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                outer.requests.append({"auth": self.headers.get("Authorization"), "body": body})
                answers = {}
                for qid in body["questions"]:
                    answer = {"type": "noul", "noul": noul_for(body)}
                    if leak:
                        answer["debug"] = f"Authorization: {self.headers.get('Authorization')}"
                    answers[qid] = answer
                payload = json.dumps(
                    {"model": served, "answers": answers, "usage": {"input_tokens": 9, "output_tokens": 1}}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/api/alpha/decisions"

    def close(self):
        self.srv.shutdown()


def test_span_01_lite_per_candidate_end_to_end_with_the_real_shape(tmp_path, items_file, monkeypatch):
    srv = _NoulServer(lambda b: {"Zoro": 0.93, "Roronoa Zoro": 0.11}[b["state"]["output"]["content"]], SPAN_SERVED, leak=True)
    monkeypatch.setenv("GLOSSARY_BAKEOFF_SPAN_01_LITE_URL", srv.url)
    try:
        _, rows, outp = _run(tmp_path, items_file, "span-01-lite", "--stage", "verify", "--only", "gold")
    finally:
        srv.close()
    assert len(srv.requests) == 2 and all(r["auth"] == f"Bearer {KEY}" for r in srv.requests)
    row = rows[0]
    assert row["error"] is None and row["parsed"] == {"scores": {"Zoro": 0.93, "Roronoa Zoro": 0.11}}
    assert row["served_model"] == SPAN_SERVED and row["usage"] == {"input_tokens": 18, "output_tokens": 2}
    assert row["raw"][0]["answer"] == {"type": "noul", "noul": 0.93}  # whitelisted: the echoed debug field is gone
    assert KEY not in outp.read_text(encoding="utf-8")
    pick = glossary_score.row_pick(row)  # the scorer's rule: best-scoring candidate if its noul >= 0.5
    assert pick.title == "Zoro" and pick.conf == 0.93


def test_span_01_lite_below_half_is_still_a_titled_pick_the_tau_sweep_abstains(tmp_path, items_file, monkeypatch):
    srv = _NoulServer(lambda b: 0.11, SPAN_SERVED)
    monkeypatch.setenv("GLOSSARY_BAKEOFF_SPAN_01_LITE_URL", srv.url)
    try:
        _, rows, _ = _run(tmp_path, items_file, "span-01-lite", "--stage", "verify", "--only", "gold")
    finally:
        srv.close()
    pick = glossary_score.row_pick(rows[0])
    assert pick.title and pick.conf == pytest.approx(0.11)  # no fixed 0.5 cut: abstention is the tau sweep's job


@pytest.mark.parametrize(
    "arm,env,served,noul,same",
    [
        ("mercury-decide", "MERCURY_DECIDE", "inception/mercury-decide-20260930", 0.9669140186318742, True),
        ("span-01-lite", "SPAN_01_LITE", SPAN_SERVED, 0.11070899, False),
        ("jev", "JEV", "typesafe/jev", 0.79, True),
        ("jev", "JEV", "typesafe/jev", 0.5, True),  # the boundary: >= 0.5 is "same entity"
        ("jev", "JEV", "typesafe/jev", 0.4999, False),
    ],
)
def test_acquire_rows_store_the_raw_noul_and_a_same_entity_flag_with_no_threshold(
    tmp_path, items_file, monkeypatch, arm, env, served, noul, same
):
    srv = _NoulServer(lambda b: noul, served, leak=True)
    monkeypatch.setenv(f"GLOSSARY_BAKEOFF_{env}_URL", srv.url)
    try:
        _, rows, outp = _run(tmp_path, items_file, arm, "--stage", "acquire")
    finally:
        srv.close()
    assert [r["id"] for r in rows] == ["acquire:Alpha Show:Nammi|Nami"]  # the quote-less pair is not sent to a third party
    r = rows[0]
    assert r["error"] is None and r["parsed"]["noul"] == noul and r["parsed"]["same_entity"] is same
    assert r["parsed"]["confidence"] == pytest.approx(max(noul, 1 - noul))
    assert r["served_model"] == served and r["raw"] == {"type": "noul", "noul": noul}
    assert KEY not in outp.read_text(encoding="utf-8")


def test_the_noul_path_never_writes_the_key_even_when_the_server_echoes_the_authorization_header(
    tmp_path, items_file, monkeypatch, capsys
):
    srv = _NoulServer(lambda b: 0.7, "typesafe/jev", leak=True)
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_URL", srv.url)
    try:
        _, _, outp = _run(tmp_path, items_file, "jev", "--stage", "acquire")
    finally:
        srv.close()
    seen = capsys.readouterr()
    assert KEY not in outp.read_text(encoding="utf-8") + seen.out + seen.err


def test_a_malformed_noul_answer_from_the_server_is_an_error_row_not_a_pick(tmp_path, items_file, monkeypatch):
    srv = _NoulServer(lambda b: 1.7, "typesafe/jev")  # out of range
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_URL", srv.url)
    try:
        _, rows, _ = _run(tmp_path, items_file, "jev", "--stage", "acquire")
    finally:
        srv.close()
    assert rows[0]["parsed"] is None and "noul" in rows[0]["error"]


# =====================================================================================
# Phase 4: framing v2 for the decision arms (a POST-HOC change, reported next to v1)
# =====================================================================================

V2_INSTRUCTION = (
    'The term "{term}" was mined from the English dub of {show}. It may be a short form, nickname, partial name or '
    "misspelling of a character, place, technique or item. Choose the wiki title it refers to. A fuller form of the same "
    "name counts as the same (for example a given name and its full name)."
)


def test_at_v2_arms_resolve_to_the_base_entry_with_framing_v2():
    base = gb.ARMS["mercury-decide"]
    v2 = gb.resolve_arm("mercury-decide@v2")
    assert v2.name == "mercury-decide@v2" and v2.framing == "v2" and v2.base == "mercury-decide"
    assert (v2.model, v2.url, v2.key_env, v2.provider, v2.kind) == (base.model, base.url, base.key_env, base.provider, base.kind)
    assert gb.resolve_arm("mercury-decide") is base and base.framing == "v1"
    for name in ("jev@v2", "span-01-lite@v2", "solar-decide-flash@v2", "pplx-decider@v2", "gpt-6-luna-decisions@v2"):
        assert gb.resolve_arm(name).framing == "v2" and name in gb.ARM_CHOICES


@pytest.mark.parametrize("bad", ["longcat-2.0@v2", "qwen-local@v2", "nemotron-super@v2", "nope@v2", "mercury-decide@v3"])
def test_only_decision_arms_have_a_v2(tmp_path, items_file, bad):
    with pytest.raises(SystemExit) as e:
        gb.main(["run", "--items", str(items_file), "--arm", bad, "--out", str(tmp_path / "o.jsonl")])
    assert e.value.code == 2


def test_the_v2_choice_question_is_the_frozen_text_over_the_candidate_titles_only(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c2", 0.81), seen)
    _, rows, _ = _run(tmp_path, items_file, "mercury-decide@v2", "--stage", "verify", "--only", "gold")
    q = seen[0]["questions"]["pick"]
    assert q["type"] == "choice" and q["criteria"] == {"c1": "Zoro", "c2": "Roronoa Zoro"}  # no `none` option
    assert q["instructions"] == V2_INSTRUCTION.format(term="Zoro", show="Alpha Show")
    assert seen[0]["state"] == {"show": "Alpha Show", "term": "Zoro"} and seen[0]["model"] == "inception/mercury-decide:free"
    r = rows[0]
    assert r["arm"] == "mercury-decide@v2" and r["framing"] == "v2" and r["order"] == "fwd" and r["error"] is None
    assert r["parsed"]["canonical"] == "Roronoa Zoro" and r["parsed"]["choice"] == "c2" and r["parsed"]["confidence"] == 0.81


def _choice_for(questions, choice, conf):
    opts = list(questions["pick"]["criteria"])
    probs = {o: (conf if o == choice else (1 - conf) / (len(opts) - 1)) for o in opts}
    return {"pick": {"type": "choice", "choice": choice, "probabilities": probs, "confidence": conf}}


def test_v2_canonical_is_always_a_title_and_reversed_order_maps_back(tmp_path, items_file, monkeypatch):
    seen = []
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c1", 0.6), seen)
    _, rows, _ = _run(tmp_path, items_file, "jev@v2", "--stage", "verify", "--only", "gold", "--reverse")
    assert list(seen[0]["questions"]["pick"]["criteria"].values()) == ["Roronoa Zoro", "Zoro"]
    assert rows[0]["order"] == "rev" and rows[0]["parsed"]["canonical"] == "Roronoa Zoro" and rows[0]["arm"] == "jev@v2"


def test_v2_skips_single_candidate_items_for_choice_arms_and_says_so(tmp_path, monkeypatch, capsys):
    p = tmp_path / "items.jsonl"
    p.write_text(
        json.dumps(_vitem("Solo", ["Solo"], gold="Solo"))
        + "\n"
        + json.dumps(_vitem("Duo", ["Duo", "Duo Jr"], gold="Duo"))
        + "\n",
        encoding="utf-8",
    )
    seen = []
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c1", 0.9), seen)
    _, rows, _ = _run(tmp_path, p, "mercury-decide@v2")
    assert [r["id"] for r in rows] == ["verify:Alpha Show:Duo"] and len(seen) == 1
    assert "skipped (single candidate" in capsys.readouterr().out
    _, rows1, _ = _run(tmp_path, p, "mercury-decide", out="v1.jsonl")  # framing v1 still asks the single-candidate item
    assert len(rows1) == 2


def test_v2_runs_no_acquire_items_and_says_so(tmp_path, items_file, monkeypatch, capsys):
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c1", 0.9))
    _, rows, _ = _run(tmp_path, items_file, "mercury-decide@v2", "--stage", "both")
    assert rows and all(r["id"].startswith("verify:") for r in rows)
    assert "skipped (not applicable): 2" in capsys.readouterr().out


def test_v2_and_v1_rows_share_one_results_file_without_colliding(tmp_path, items_file, monkeypatch):
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c1", 0.9) if "pick" in q else {})
    out = tmp_path / "res" / "both.jsonl"
    for arm in ("mercury-decide", "mercury-decide@v2"):
        gb.main(["run", "--items", str(items_file), "--arm", arm, "--out", str(out), "--stage", "verify", "--only", "gold"])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert sorted(r["arm"] for r in rows) == ["mercury-decide", "mercury-decide@v2"]
    assert "framing" not in next(r for r in rows if r["arm"] == "mercury-decide")  # v1 rows keep their old shape
    gb.main(
        [
            "run",
            "--items",
            str(items_file),
            "--arm",
            "mercury-decide@v2",
            "--out",
            str(out),
            "--stage",
            "verify",
            "--only",
            "gold",
        ]
    )
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2  # resume skipped the finished v2 row


V1_QUESTION = {
    "type": "choice",
    "instructions": (
        'A term was mined from the English dub of "Alpha Show". Pick the candidate wiki page that is the '
        "SAME named entity as the "
        'term "Zoro". Choose "none" if no candidate is the same entity.'
    ),
    "criteria": {"c1": "Zoro", "c2": "Roronoa Zoro", "none": "no candidate is the same named entity"},
}


def test_v1_framing_is_unchanged_byte_for_byte(tmp_path, items_file, monkeypatch):
    """GUARD: passes on the old code."""
    seen = []
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c1", 0.9), seen)
    _, rows, _ = _run(tmp_path, items_file, "mercury-decide", "--stage", "verify", "--only", "gold")
    assert seen[0]["questions"] == {"pick": V1_QUESTION} and seen[0]["state"] == {"show": "Alpha Show", "term": "Zoro"}
    assert set(rows[0]) == {"id", "arm", "order", "raw", "parsed", "latency_s", "usage", "error", "served_model"}
    assert set(rows[0]["parsed"]) == {"choice", "canonical", "probabilities", "confidence"}


def test_span_v2_asks_one_noul_per_candidate_with_the_candidate_only_in_the_output(tmp_path, items_file, monkeypatch):
    seen = []
    scores = {"Zoro": 0.06, "Roronoa Zoro": 0.09}  # both far below 0.5, as observed on the real data

    def answer(model, state, questions):
        return {next(iter(questions)): {"type": "noul", "noul": scores[state["output"]["content"]]}}

    _fake_decide(monkeypatch, answer, seen)
    _, rows, _ = _run(tmp_path, items_file, "span-01-lite@v2", "--stage", "verify", "--only", "gold")
    assert len(seen) == 2 and {s["model"] for s in seen} == {"respan/span-01-lite"}
    q = next(iter(seen[0]["questions"].values()))
    assert q["type"] == "noul" and q["instructions"] == "Is the output a correct answer to the input?"
    assert q["criteria"] == {"true": "the output is the wiki title the term refers to", "false": "it is not"}
    expected_input = V2_INSTRUCTION.format(term="Zoro", show="Alpha Show")
    assert [s["state"]["input"] for s in seen] == [[{"role": "user", "content": expected_input}]] * 2  # no candidate in the input
    assert [s["state"]["output"] for s in seen] == [
        {"role": "assistant", "content": "Zoro"},
        {"role": "assistant", "content": "Roronoa Zoro"},
    ]
    r = rows[0]
    assert r["arm"] == "span-01-lite@v2" and r["framing"] == "v2"
    assert r["parsed"]["canonical"] == "Roronoa Zoro" and r["parsed"]["confidence"] == 0.09  # best-scoring, whatever its size
    assert r["parsed"]["scores"] == scores
    pick = glossary_score.row_pick(r)
    assert pick.title == "Roronoa Zoro" and pick.conf == 0.09  # no 0.5 cutoff: abstention is decided by tau at score time


def test_the_env_override_for_a_v2_arm_uses_the_base_arms_name(tmp_path, items_file, monkeypatch):
    srv = _NoulServer(lambda b: 0.5, "typesafe/jev")
    monkeypatch.setenv("GLOSSARY_BAKEOFF_JEV_URL", srv.url)
    try:
        arm = gb.resolve_arm("jev@v2")
        assert gb._arm_setting(arm, "url") == srv.url
    finally:
        srv.close()


def test_the_request_estimate_for_a_v2_arm_leaves_out_single_candidate_and_acquire_items(tmp_path, monkeypatch, capsys):
    p = tmp_path / "est.jsonl"
    items = (
        [_vitem("Solo", ["Solo"], gold="Solo")]
        + [_vitem(f"D{k}", [f"D{k}", f"D{k} Jr"]) for k in range(4)]
        + [_aitem("A", "B", {"variant": ["x"], "canonical": ["y"]})]
    )
    p.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    _fake_decide(monkeypatch, lambda m, s, q: _choice_for(q, "c1", 0.9))
    _run(tmp_path, p, "jev@v2")
    assert "at most 12 request(s) (4 item(s)" in capsys.readouterr().out  # 4 two-candidate items x 3
