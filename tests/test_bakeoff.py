"""Unit tests for tools/bakeoff.py's input loading.

The documented `--raw` path needs a `dump_whisper.py` capture that does not exist in this
repo, which made the bake-off unrunnable without re-transcribing an episode on the GPU.
`--conf` closes that: a production `<stem>.dubtitles.conf.json` already carries every
field `repair.is_target()` reads (text, avg_logprob, no_speech_prob, word_probs), and it
is the *same* file `repair.py` consumes in production -- so the bake-off judges the models
on exactly the lines the live pipeline would have sent them, with no GPU and no reflow
re-derivation. Ollama calls are not exercised here (no network in tests).
"""

import json

import pytest

import tools.bakeoff as bo


def _conf_row(text="Zolo drew his blade.", lp=-0.9, nsp=0.05, probs=None):
    row = {"start": 1.0, "end": 3.0, "avg_logprob": lp, "no_speech_prob": nsp, "text": text}
    if probs is not None:
        row["word_probs"] = probs
    return row


def _write(tmp_path, rows, name="ep.dubtitles.conf.json"):
    p = tmp_path / name
    p.write_text(json.dumps(rows))
    return str(p)


# --- conf.json loading --------------------------------------------------------


def test_load_cards_from_conf_returns_the_rows_as_cards(tmp_path):
    rows = [_conf_row("First line."), _conf_row("Second line.")]
    cards = bo.load_cards(None, _write(tmp_path, rows))
    assert [c["text"] for c in cards] == ["First line.", "Second line."]
    assert cards[0]["avg_logprob"] == -0.9 and cards[0]["no_speech_prob"] == 0.05


def test_load_cards_from_conf_preserves_word_probs(tmp_path):
    """word_probs is what repair.has_low_prob_word() reads -- dropping it would silently
    change which lines qualify as repair targets, so the bake-off would judge the models
    on a different set of lines than production sends them."""
    cards = bo.load_cards(None, _write(tmp_path, [_conf_row(probs=[0.95, 0.11])]))
    assert cards[0]["word_probs"] == [0.95, 0.11]


def test_load_cards_from_conf_tolerates_rows_without_word_probs(tmp_path):
    cards = bo.load_cards(None, _write(tmp_path, [_conf_row()]))
    assert "word_probs" not in cards[0]


def test_load_cards_from_conf_rejects_a_non_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(SystemExit):
        bo.load_cards(None, str(p))


def test_load_cards_from_conf_rejects_rows_missing_text(tmp_path):
    """A conf.json without `text` would produce empty prompts and a meaningless bake-off;
    fail loudly instead."""
    with pytest.raises(SystemExit):
        bo.load_cards(None, _write(tmp_path, [{"start": 0, "end": 1}]))


# --- input selection ----------------------------------------------------------


def test_load_cards_requires_one_input(tmp_path):
    with pytest.raises(SystemExit):
        bo.load_cards(None, None)


def test_load_cards_rejects_both_inputs(tmp_path):
    """--raw and --conf are different stages of the pipeline; silently preferring one
    would make the reported comparison ambiguous."""
    with pytest.raises(SystemExit):
        bo.load_cards("raw.json", _write(tmp_path, [_conf_row()]))


# --- the targets it selects are the ones production would send ----------------


def test_conf_cards_feed_the_real_is_target_predicate(tmp_path):
    """End-to-end on the selection logic: a clean high-confidence line is not a target,
    a low-logprob line is -- using repair.is_target itself, not a copy."""
    import glossary
    import repair

    gloss = glossary.load("")
    rows = [_conf_row("A perfectly clear line.", lp=-0.1, nsp=0.01), _conf_row("grbled nnsense here", lp=-1.4, nsp=0.02)]
    cards = bo.load_cards(None, _write(tmp_path, rows))
    targets = [c for c in cards if repair.is_target(c, gloss)]
    assert [c["text"] for c in targets] == ["grbled nnsense here"]


# --- llama.cpp candidates -----------------------------------------------------
#
# Some models can't be served by Ollama at all -- Nanbeige's GGUF needs a patched
# llama.cpp (`ollama create` fails with "failed to validate GGUF ... without
# compatibility patches"), which is why it runs in its own container. repair.py already
# supports a llama.cpp backend (REPAIR_BACKEND=llamacpp); the bake-off has to speak the
# same protocol or those models simply can't be evaluated.


def test_parse_llamacpp_specs_builds_a_name_to_url_map():
    m = bo.parse_llamacpp_specs(["nanbeige=http://host:8090/completion"])
    assert m == {"nanbeige": "http://host:8090/completion"}


def test_parse_llamacpp_specs_rejects_a_spec_without_a_url():
    with pytest.raises(SystemExit):
        bo.parse_llamacpp_specs(["nanbeige"])


def test_llamacpp_body_matches_production_repair(monkeypatch):
    """The bake-off must send what repair.llm_llamacpp sends, or it measures a different
    configuration than the one that would ship: no model selector (the server has one
    model loaded), n_predict/stop set, and the reply read from "content" not "response"."""
    seen = {}

    def fake_post(url, body, timeout=180):
        seen["url"], seen["body"] = url, body
        return {"content": ' "Zoro drew his blade." \n trailing junk'}

    monkeypatch.setattr(bo, "_post_json", fake_post)
    out, dt = bo.ask_llamacpp("http://host:8090/completion", "PROMPT")
    assert seen["url"] == "http://host:8090/completion"
    assert seen["body"]["prompt"] == "PROMPT"
    assert seen["body"]["temperature"] == 0
    assert "model" not in seen["body"]  # llama.cpp has no model selector
    assert seen["body"]["stop"] == ["\n"]
    assert out == "Zoro drew his blade."  # first line, unquoted, stripped
    assert dt >= 0


def test_ask_routes_llamacpp_models_away_from_ollama(monkeypatch):
    """A model named in --llamacpp must not be posted to the Ollama endpoint (it isn't
    there; it would come back as an <ERROR> row and read like a model failure)."""
    calls = []
    monkeypatch.setattr(bo, "ask_ollama", lambda url, m, p: (calls.append(("ollama", m)), ("o", 0.1))[1])
    monkeypatch.setattr(bo, "ask_llamacpp", lambda url, p: (calls.append(("llamacpp", url)), ("l", 0.2))[1])
    lc = {"nanbeige": "http://host:8090/completion"}
    assert bo.ask("http://ollama/api/generate", "qwen3.5:9b", "p", lc)[0] == "o"
    assert bo.ask("http://ollama/api/generate", "nanbeige", "p", lc)[0] == "l"
    assert calls == [("ollama", "qwen3.5:9b"), ("llamacpp", "http://host:8090/completion")]


# --- llama.cpp CHAT mode ------------------------------------------------------
#
# repair.llm_llamacpp posts a RAW prompt to /completion, which applies no chat template.
# For a templated instruct model that yields garbage -- Nanbeige returns nothing but
# newlines. /v1/chat/completions applies the template, and this fork additionally needs
# enable_thinking=false or it spends its whole budget on reasoning_content and returns an
# empty message (verified: empty after 114s at max_tokens=512; correct output in 4.3s with
# thinking off). Chat mode exists so such a model can be judged on its real behaviour.


def test_llamacpp_chat_applies_template_and_disables_thinking(monkeypatch):
    seen = {}

    def fake_post(url, body, timeout=180):
        seen["url"], seen["body"] = url, body
        return {"choices": [{"message": {"content": '  "Zoro drew his blade."\nextra'}}]}

    monkeypatch.setattr(bo, "_post_json", fake_post)
    out, _ = bo.ask_llamacpp_chat("http://host:8090/v1/chat/completions", "PROMPT")
    assert seen["body"]["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert out == "Zoro drew his blade."


def test_llamacpp_chat_reports_an_empty_reply_rather_than_silently_scoring_it(monkeypatch):
    """An empty content with reasoning_content populated means thinking was not actually
    disabled. Returning "" would look like the model declined to change the line -- i.e.
    a perfect no-op score -- so it has to be visibly flagged instead."""
    monkeypatch.setattr(
        bo,
        "_post_json",
        lambda u, b, timeout=180: {"choices": [{"message": {"content": "", "reasoning_content": "thinking..."}}]},
    )
    out, _ = bo.ask_llamacpp_chat("http://host/v1/chat/completions", "P")
    assert out.startswith("<EMPTY")


def test_ask_prefers_chat_endpoint_when_given(monkeypatch):
    monkeypatch.setattr(bo, "ask_ollama", lambda u, m, p: ("o", 0.1))
    monkeypatch.setattr(bo, "ask_llamacpp", lambda u, p: ("raw", 0.1))
    monkeypatch.setattr(bo, "ask_llamacpp_chat", lambda u, p: ("chat", 0.1))
    assert bo.ask("http://o", "nb", "p", {"nb": "u"}, {})[0] == "raw"
    assert bo.ask("http://o", "nb", "p", {}, {"nb": "u"})[0] == "chat"


# --- results must survive a timeout -------------------------------------------
#
# bakeoff buffered every result and printed only at the very end, so a run that hit a
# wall-clock limit lost ALL of it -- twice, at 111 and 25 minutes, against models slow
# enough to blow any sane budget. Emitting each model's block as soon as that model
# finishes means a kill during model 3 still yields models 1 and 2.


def test_format_model_block_pairs_each_target_with_its_output():
    targets = [{"text": "zolo drew"}, {"text": "nami said"}]
    outs = ["Zoro drew", "Nami said"]
    block = bo.format_model_block("qwen3.5:9b", targets, outs, 4.0)
    assert "qwen3.5:9b" in block
    assert "zolo drew" in block and "Zoro drew" in block
    assert "nami said" in block and "Nami said" in block
    assert "2.0" in block  # avg latency per line


def test_format_model_block_survives_fewer_outputs_than_targets():
    """A model killed mid-way still gets a block for what it did produce, rather than
    raising IndexError and destroying the completed models' results too."""
    targets = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    block = bo.format_model_block("m", targets, ["A"], 1.0)
    assert "A" in block
    assert "<no result>" in block


# --- scoring: the computable half of the judgment -----------------------------
#
# The candidate pool is ~19 models; at --limit 15 that is ~285 line pairs to read by
# hand. docs/model-candidates-4-5gb-vram.md names three judging signals -- safe-fix
# count, name-edit count and inertness -- and only safe-fix genuinely needs a human.
# The rest are computed here so the owner hand-judges a shortlist instead of the pool.
# No live inference is exercised: score_model is pure over (targets, outputs, glossary).

import glossary as _glossary  # noqa: E402
import repair as _repair  # noqa: E402


def _gloss(names=("Zoro", "Nami"), fixes=None):
    return _glossary.load_dict({"names": list(names), "hard_fixes": dict(fixes or {})})


def _card(text, start=1.0, end=5.0):
    return {"text": text, "start": start, "end": end}


ORIG = "Zolo drew his blade."
FIXED = "Zoro drew his blade."
BLOATED = "Zoro drew his blade and then ran away very fast."


def test_a_fully_inert_model_scores_inert_and_admits_nothing():
    """nanbeige4.2-3b's measured failure: 0 safe fixes across 120 targets, the input
    returned verbatim. That must read as a total failure, not as a clean no-op."""
    targets = [_card(ORIG), _card("Nami waved goodbye.")]
    s = bo.score_model("nanbeige", targets, [ORIG, "Nami waved goodbye."], 4.0, _gloss())
    assert s["inert"] == 2
    assert s["inert_rate"] == 1.0
    assert s["changed"] == 0
    assert s["admitted"] == 0
    assert s["admitted_rate"] == 0.0
    assert s["name_edits"] == 0


def test_inertness_ignores_case_and_spacing():
    """A model that only re-spaced or re-cased the line changed nothing of substance;
    counting it as a change would inflate every other rate against it."""
    s = bo.score_model("m", [_card(ORIG)], ["zolo   drew his blade."], 1.0, _gloss())
    assert s["inert"] == 1
    assert s["changed"] == 0


def test_a_model_that_rewrites_everything_is_not_inert():
    targets = [_card(ORIG), _card("Nami waved goodbye.")]
    outs = [FIXED, "Nami waved farewell."]
    s = bo.score_model("rewriter", targets, outs, 4.0, _gloss())
    assert s["inert"] == 0
    assert s["inert_rate"] == 0.0
    assert s["changed"] == 2
    assert s["change_rate"] == 1.0


def test_admitted_is_repair_accept_repairs_own_verdict():
    """The bar is production's gate, not a bespoke one: a glossary name fix is admitted,
    a rewrite that blows accept_repair's length band is not."""
    targets = [_card(ORIG), _card(ORIG)]
    s = bo.score_model("m", targets, [FIXED, BLOATED], 2.0, _gloss())
    assert _repair.accept_repair(ORIG, FIXED, "", 4.0, _gloss()) is True
    assert _repair.accept_repair(ORIG, BLOATED, "", 4.0, _gloss()) is False
    assert s["admitted"] == 1
    assert s["admitted_rate"] == 0.5


def test_an_inert_line_is_never_admitted():
    """accept_repair refuses new == orig outright; the two signals must not disagree,
    or a fully inert model could show a non-zero ship rate."""
    s = bo.score_model("m", [_card(ORIG)], [ORIG], 1.0, _gloss())
    assert s["inert"] == 1 and s["admitted"] == 0


def test_error_and_empty_outputs_are_counted_never_read_as_leaving_the_line_alone():
    """<ERROR>/<EMPTY> mean the model produced nothing. Scoring them as "unchanged"
    would turn a dead backend into a perfect inertness-free no-op -- a silent false pass."""
    targets = [_card(ORIG), _card(ORIG), _card(ORIG)]
    outs = ["<ERROR timed out>", "<EMPTY thinking not disabled?>", FIXED]
    s = bo.score_model("m", targets, outs, 3.0, _gloss())
    assert s["errors"] == 1
    assert s["empties"] == 1
    assert s["error_rate"] == pytest.approx(2 / 3)
    assert s["inert"] == 0  # NOT counted as "left the line alone"
    assert s["changed"] == 1
    assert s["admitted"] == 1


def test_a_glossary_name_correction_counts_as_a_name_edit():
    s = bo.score_model("m", [_card(ORIG)], [FIXED], 1.0, _gloss())
    assert s["name_edits"] == 1


def test_a_reword_that_touches_no_proper_noun_is_not_a_name_edit():
    s = bo.score_model("m", [_card("It was a very long day.")], ["It was a really long day."], 1.0, _gloss())
    assert s["changed"] == 1
    assert s["name_edits"] == 0


def test_a_fabricated_name_still_counts_as_a_name_edit():
    """Name-edit count measures how often the model TOUCHES a name -- including badly.
    `Zolo` -> `Zorro` is an edit the owner needs to see, and accept_repair rejects it,
    so the two columns together separate "edits names well" from "edits names at all"."""
    s = bo.score_model("m", [_card(ORIG)], ["Zorro drew his blade."], 1.0, _gloss())
    assert s["name_edits"] == 1
    assert s["admitted"] == 0  # invents_name refuses a fabricated proper noun


def test_missing_results_are_reported_not_scored_as_success():
    """A model killed mid-run produced fewer outputs than targets. Padding the tail with
    "unchanged" would score the kill as inertness; dropping it would hide the shortfall."""
    targets = [_card(ORIG), _card(ORIG), _card(ORIG)]
    s = bo.score_model("m", targets, [FIXED], 1.0, _gloss())
    assert s["targets"] == 3
    assert s["scored"] == 1
    assert s["missing"] == 2
    assert s["admitted_rate"] == 1.0  # over what it actually produced


def test_latency_is_averaged_over_the_lines_actually_completed():
    s = bo.score_model("m", [_card(ORIG), _card(ORIG)], [FIXED, FIXED], 9.0, _gloss())
    assert s["avg_latency_s"] == pytest.approx(4.5)


def test_an_empty_run_summarises_without_raising():
    """No targets at all (a conf.json where nothing qualified) must still produce a row."""
    s = bo.score_model("m", [], [], 0.0, _gloss())
    assert s["targets"] == 0 and s["scored"] == 0
    assert s["inert_rate"] is None
    assert s["admitted_rate"] is None
    assert s["avg_latency_s"] is None
    ranked = bo.rank_models([s])
    assert bo.format_summary(ranked)  # renders rather than dividing by zero


def test_a_card_without_a_duration_is_flagged_rather_than_silently_gated():
    """accept_repair REQUIRES dur -- C2: a caller that does not know the card must not
    skip the fit check. An undatable card is reported, not quietly counted either way."""
    s = bo.score_model("m", [{"text": ORIG}], [FIXED], 1.0, _gloss())
    assert s["no_duration"] == 1
    assert s["admitted"] == 0


# --- ranking + the summary table ----------------------------------------------


def _score(model, **kw):
    base = dict(
        model=model,
        targets=10,
        scored=10,
        missing=0,
        inert=0,
        changed=10,
        errors=0,
        empties=0,
        admitted=5,
        name_edits=3,
        no_duration=0,
        inert_rate=0.0,
        change_rate=1.0,
        error_rate=0.0,
        admitted_rate=0.5,
        name_edit_rate=0.3,
        avg_latency_s=2.0,
    )
    base.update(kw)
    return base


def test_ranking_puts_the_higher_ship_rate_first():
    ranked = bo.rank_models([_score("low", admitted=2, admitted_rate=0.2), _score("high", admitted=8, admitted_rate=0.8)])
    assert [r["model"] for r in ranked] == ["high", "low"]
    assert ranked[0]["rank"] == 1


def test_ranking_breaks_ties_on_latency():
    ranked = bo.rank_models([_score("slow", avg_latency_s=30.0), _score("fast", avg_latency_s=1.0)])
    assert [r["model"] for r in ranked] == ["fast", "slow"]


def test_every_model_appears_in_the_summary_even_when_it_scores_zero():
    """The shortlist is a recommendation, not a filter. A model dropped from the table
    is a model the owner cannot see was tested -- and the doc's whole point is that
    inertness is a RESULT, not an absence of one."""
    scores = [
        _score("good", admitted=9, admitted_rate=0.9),
        _score("inert", inert=10, inert_rate=1.0, changed=0, change_rate=0.0, admitted=0, admitted_rate=0.0, name_edits=0),
        _score("broken", errors=10, error_rate=1.0, changed=0, change_rate=0.0, admitted=0, admitted_rate=0.0),
    ]
    out = bo.format_summary(bo.rank_models(scores))

    # The name appearing SOMEWHERE in the summary is not the claim -- the per-model notes and
    # the shortlist both mention models too, so "in out" passes even when the ranked table has
    # been filtered. Checked here against the TABLE, which is what the docstring above means:
    # rows between the column header and the legend that follows it.
    table = []
    for line in out.splitlines():
        if line.lstrip().startswith("#") and "model" in line:
            table = []  # header: start collecting
            continue
        if table and not line.strip():
            break  # blank line ends the table
        if table or line.strip()[:1].isdigit():
            table.append(line)
    rendered = "\n".join(table)

    for m in ("good", "inert", "broken"):
        assert m in rendered, f"{m} is missing from the ranked table, not merely ranked low"
    assert rendered.count("\n") + 1 == 3, "every model gets a row, no more and no fewer"


def test_a_model_that_ranks_low_is_told_why():
    scores = [
        _score("good", admitted=9, admitted_rate=0.9),
        _score("inert", inert=10, inert_rate=1.0, changed=0, change_rate=0.0, admitted=0, admitted_rate=0.0, name_edits=0),
        _score("broken", errors=10, error_rate=1.0, changed=0, change_rate=0.0, admitted=0, admitted_rate=0.0),
    ]
    ranked = bo.rank_models(scores)
    by = {r["model"]: r for r in ranked}
    assert "inert" in by["inert"]["note"].lower()
    assert by["broken"]["note"]
    assert "<ERROR" in by["broken"]["note"] or "error" in by["broken"]["note"].lower()


def test_the_shortlist_names_only_models_with_something_to_judge():
    scores = [
        _score("good", admitted=9, admitted_rate=0.9),
        _score("inert", inert=10, inert_rate=1.0, changed=0, change_rate=0.0, admitted=0, admitted_rate=0.0),
    ]
    ranked = bo.rank_models(scores)
    by = {r["model"]: r for r in ranked}
    assert by["good"]["shortlisted"] is True
    assert by["inert"]["shortlisted"] is False
    out = bo.format_summary(ranked)
    assert "SHORTLIST" in out.upper()


def test_the_shortlist_is_capped_but_the_table_is_not():
    scores = [_score(f"m{i}", admitted_rate=1.0 - i / 100) for i in range(8)]
    ranked = bo.rank_models(scores, shortlist_n=3)
    assert sum(1 for r in ranked if r["shortlisted"]) == 3
    assert len(ranked) == 8
    out = bo.format_summary(ranked)
    for i in range(8):
        assert f"m{i}" in out


def test_a_shortlist_with_no_eligible_model_says_so_instead_of_printing_nothing():
    scores = [_score("inert", inert=10, inert_rate=1.0, changed=0, admitted=0, admitted_rate=0.0)]
    out = bo.format_summary(bo.rank_models(scores))
    assert "none" in out.lower()


def test_the_summary_states_whatever_bounded_the_run():
    """No silent caps: a --limit, a skipped model or a mid-run kill must be visible in
    the report, or the owner reads a partial result as a complete one."""
    out = bo.format_summary(bo.rank_models([_score("m")]), bounds=["--limit 15 of 120 targets"])
    assert "--limit 15 of 120 targets" in out


def test_changing_every_line_is_not_called_over_rewriting_on_too_small_a_sample():
    """`is_target` hands the models pre-selected SUSPECT lines, so on a handful of them
    "changed all of them" is what a good model does. Flagging it as the doc's
    rewrites-everything failure at --limit 2 would libel the best candidate in the pool."""
    ranked = bo.rank_models([_score("m", targets=4, scored=4, changed=4, change_rate=1.0, admitted=2, admitted_rate=0.5)])
    assert "left nothing alone" not in ranked[0]["note"]


def test_changing_every_line_is_flagged_once_there_are_enough_lines_to_mean_it():
    ranked = bo.rank_models([_score("m", targets=20, scored=20, changed=20, change_rate=1.0, admitted=10, admitted_rate=0.5)])
    assert "left nothing alone" in ranked[0]["note"]


# --- no silent caps ------------------------------------------------------------
#
# Anything that narrowed what was measured has to reach the report. A --limit, a model
# killed part-way, a card the ship gate could not be run on: each makes the numbers mean
# less than they look, and a partial run read as a complete one is how a candidate gets
# locked in on evidence that was never gathered.


def test_a_limit_that_truncated_the_targets_is_reported():
    b = bo.coverage_bounds([], list(range(120)), list(range(15)), 15, _gloss())
    assert any("15" in x and "120" in x for x in b)


def test_an_empty_glossary_is_reported_because_the_name_column_cannot_work():
    b = bo.coverage_bounds([], [1], [1], 15, _gloss(names=[]))
    assert any("glossary" in x.lower() for x in b)


def test_a_model_killed_part_way_is_reported():
    b = bo.coverage_bounds([_score("slowpoke", targets=15, scored=6, missing=9)], [1] * 15, [1] * 15, 15, _gloss())
    assert any("slowpoke" in x and "6" in x for x in b)


def test_cards_the_ship_gate_could_not_run_on_are_reported():
    b = bo.coverage_bounds([_score("m", no_duration=3)], [1] * 10, [1] * 10, 15, _gloss())
    assert any("duration" in x for x in b)


def test_an_unbounded_run_reports_nothing_bounded_it():
    assert bo.coverage_bounds([_score("m")], [1] * 10, [1] * 10, 15, _gloss()) == []


def test_a_partial_model_run_is_flagged_in_its_row():
    ranked = bo.rank_models([_score("killed", scored=4, missing=6)])
    assert "4" in ranked[0]["note"] and "10" in ranked[0]["note"]
