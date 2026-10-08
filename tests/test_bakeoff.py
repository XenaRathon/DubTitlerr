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


def test_spread_sampling_reaches_the_whole_episode_not_just_the_opening():
    """`--limit N` took targets[:N], which is the first N in CARD ORDER -- and an episode
    opens with its theme song. Whisper is least confident on sung lyrics, so songs are
    over-represented among targets to begin with; the first 15 targets of One Pace S31E06
    were all opening-song lines, with not one proper noun among them.

    That made a whole 8-model bake-off unable to measure the thing it exists to measure:
    every model scored 0% name edits because there were no names to edit.

    Breaks if sampling goes back to a head slice: the selected indices would cluster at the
    start instead of spanning the episode."""
    targets = [{"text": f"line {i}", "start": float(i)} for i in range(100)]

    picked = bo.sample_targets(targets, 10, "spread")

    assert len(picked) == 10
    assert picked[0] is targets[0], "the first target is still included"
    idx = [targets.index(p) for p in picked]
    assert idx == sorted(idx), "sampling preserves episode order"
    assert max(idx) > 80, "the sample must reach the end of the episode, not stop at the front"
    assert len(set(idx)) == 10, "no target is sampled twice"


def test_head_sampling_is_still_available_and_unchanged():
    """The old behaviour stays reachable, so a run can be reproduced exactly as it was."""
    targets = [{"text": f"line {i}"} for i in range(100)]
    assert bo.sample_targets(targets, 5, "head") == targets[:5]


def test_sampling_fewer_targets_than_asked_for_returns_them_all():
    """An episode with 3 targets and --limit 15 must not raise or pad."""
    targets = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    assert bo.sample_targets(targets, 15, "spread") == targets


def test_comparison_puts_every_model_on_the_same_line_side_by_side():
    """Ship rate alone cannot rank models: 40% shipped could be 40% garbage, and 13% could be
    a model correctly leaving good lines alone. The only way to tell is to read what each
    model actually did to the SAME line.

    A 6GB card holds one model at a time, so the pool runs one model per invocation and the
    side-by-side `bakeoff.py` was built to print is lost across separate files. This rebuilds
    it from the per-model runs.

    Breaks if a model's answer is dropped, if answers are misaligned against the original, or
    if a model that failed on a line is silently omitted rather than shown as failed."""
    runs = {
        "alpha": [
            {"orig": "i saw spondum", "out": "I saw Spandam.", "admitted": True},
            {"orig": "dothamingo laughed", "out": "dothamingo laughed", "admitted": False},
        ],
        "beta": [
            {"orig": "i saw spondum", "out": "I saw a phantom.", "admitted": True},
            {"orig": "dothamingo laughed", "out": "Doflamingo laughed.", "admitted": True},
        ],
        "gamma": [
            {"orig": "i saw spondum", "out": "<ERROR timeout>", "admitted": False},
            {"orig": "dothamingo laughed", "out": "Doflamingo laughed.", "admitted": True},
        ],
    }

    out = bo.format_comparison(runs)

    assert "i saw spondum" in out and "dothamingo laughed" in out
    for model in runs:
        assert model in out
    assert "I saw Spandam." in out and "I saw a phantom." in out
    assert "<ERROR timeout>" in out, "a failed call must be shown, not omitted"

    # the two originals must appear as separate blocks, each carrying all three models.
    # split()[0] is the header, which carries no ORIG: of its own.
    assert out.count("ORIG:") == 2, "one block per original line"
    blocks = out.split("ORIG:")[1:]
    for b in blocks:
        for model in runs:
            assert model in b, f"{model} missing from a comparison block"


def test_comparison_marks_which_answers_would_ship():
    """The reader needs to know which changes passed production's gate, because an unshipped
    change is a proposal the pipeline would have thrown away -- judging it as if it shipped
    would blame a model for a line no viewer would ever see."""
    runs = {
        "alpha": [{"orig": "a line", "out": "A line.", "admitted": True}],
        "beta": [{"orig": "a line", "out": "Some other thing entirely.", "admitted": False}],
    }
    out = bo.format_comparison(runs)
    alpha_line = [ln for ln in out.splitlines() if "alpha" in ln][0]
    beta_line = [ln for ln in out.splitlines() if "beta" in ln][0]
    assert alpha_line != beta_line
    assert "ship" in out.lower() or "✓" in out


# --- openai-compatible mode ----------------------------------------------------
#
# Mirrors repair.llm_openai: same body, same Bearer + User-Agent headers, the key read by
# env-var NAME. A 429 is the provider throttling us, which says nothing about the model, so
# it must not be scored as an empty reply (<EMPTY>) -- it gets its own visible marker.

import urllib.error  # noqa: E402

_KEY = "sk-bakeoff-SECRET-456"


def _http_error(code, retry_after=None):
    hdrs = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("http://x", code, "err", hdrs, None)


def _ok(content="Zoro drew his blade.", **extra):
    return {"choices": [{"message": {"content": content, **extra}}]}


def test_openai_request_shape(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    seen = {}

    def fake_post(url, body, timeout=180, headers=None, **kw):
        seen.update(url=url, body=body, headers=headers)
        return _ok(' "Zoro drew his blade."\nnoise')

    monkeypatch.setattr(bo, "_post_json", fake_post)
    out, _ = bo.ask_openai("https://api.x/v1/chat/completions", "vendor/m", "PROMPT", "TEST_BAKE_KEY", {"enable_thinking": False})
    assert out == "Zoro drew his blade."
    assert seen["url"] == "https://api.x/v1/chat/completions"
    assert seen["headers"]["Authorization"] == f"Bearer {_KEY}"
    assert seen["headers"]["User-Agent"] == "DubTitlerr/repair"
    b = seen["body"]
    assert b["model"] == "vendor/m" and b["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert b["temperature"] == 0 and b["max_tokens"] == 1024
    assert "chat_template_kwargs" not in b and b["enable_thinking"] is False


def test_openai_ignores_reasoning_content_and_flags_empty(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    monkeypatch.setattr(bo, "_post_json", lambda u, b, timeout=180, headers=None, **kw: _ok("Answer.", reasoning_content="think"))
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")[0] == "Answer."
    monkeypatch.setattr(bo, "_post_json", lambda u, b, timeout=180, headers=None, **kw: _ok("", reasoning_content="think"))
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")[0].startswith("<EMPTY")


def test_openai_missing_key_is_an_error_and_never_posts(monkeypatch):
    monkeypatch.delenv("TEST_BAKE_KEY", raising=False)
    monkeypatch.setattr(bo, "_post_json", lambda *a, **k: pytest.fail("must not post"))
    out, _ = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert out.startswith("<ERROR") and "TEST_BAKE_KEY" in out


def test_openai_error_text_never_contains_the_key(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)

    def boom(u, b, timeout=180, headers=None, **kw):
        raise _http_error(500)

    monkeypatch.setattr(bo, "_post_json", boom)
    out, _ = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert out.startswith("<ERROR") and _KEY not in out


def test_openai_429_retries_once_honouring_retry_after_then_succeeds(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    calls, slept = [], []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(429, "7")
        return _ok("Fixed.")

    monkeypatch.setattr(bo, "_post_json", fake_post)
    monkeypatch.setattr(bo.time, "sleep", slept.append)
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")[0] == "Fixed."
    assert len(calls) == 2 and slept == [7.0]


def test_openai_429_retry_after_beyond_60s_falls_back(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    slept = []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        raise _http_error(429, "3600")

    monkeypatch.setattr(bo, "_post_json", fake_post)
    monkeypatch.setattr(bo.time, "sleep", slept.append)
    bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert slept == [5.0]  # out of the 0..60 range -> the 5 s fallback, not a cap


def test_openai_persistent_429_is_reported_rate_limited_not_empty(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    calls = []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        calls.append(1)
        raise _http_error(429)

    monkeypatch.setattr(bo, "_post_json", fake_post)
    monkeypatch.setattr(bo.time, "sleep", lambda s: None)
    out, _ = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert len(calls) == 2  # exactly one retry
    assert "rate-limited" in out and "429" in out
    assert not out.startswith("<EMPTY")
    # and it scores as a dead call, never as the model leaving the line alone
    s = bo.score_model("m", [{"text": "x", "start": 0, "end": 2}], [out], 1.0, _glossary.load(""))
    assert s["errors"] == 1 and s["inert"] == 0


def test_openai_records_usage_including_cached_tokens(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    usage = {"prompt_tokens": 100, "completion_tokens": 9, "prompt_tokens_details": {"cached_tokens": 64}}
    monkeypatch.setattr(bo, "_post_json", lambda u, b, timeout=180, headers=None, **kw: {**_ok("x"), "usage": usage})
    sink = []
    bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY", usage_sink=sink)
    assert sink == [{"prompt_tokens": 100, "completion_tokens": 9, "cached_tokens": 64}]
    monkeypatch.setattr(bo, "_post_json", lambda u, b, timeout=180, headers=None, **kw: _ok("x"))
    bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY", usage_sink=sink)
    assert sink[1] is None  # one entry per call, so the sink stays aligned with outs


def test_ask_routes_openai_models(monkeypatch):
    seen = []
    monkeypatch.setattr(bo, "ask_openai", lambda *a, **k: seen.append((a, k)) or ("o", 0.1))
    cfg = {"url": "https://api.x/v1/chat/completions", "key_env": "K", "extra_body": {"a": 1}}
    assert bo.ask("http://o", "m", "p", openai=cfg)[0] == "o"
    assert seen[0][0][:5] == ("https://api.x/v1/chat/completions", "m", "p", "K", {"a": 1})


def test_parse_extra_body_arg():
    assert bo.parse_extra_body("") == {}
    assert bo.parse_extra_body('{"a": 1}') == {"a": 1}
    with pytest.raises(SystemExit):
        bo.parse_extra_body("{bad")
    with pytest.raises(SystemExit):
        bo.parse_extra_body("[1]")


def test_main_openai_mode_writes_token_usage_into_the_json_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    conf = _write(tmp_path, [_conf_row("grbled nnsense here", lp=-1.4, nsp=0.02)])
    out_json = tmp_path / "res.json"
    seen = {}

    def fake_post(url, body, timeout=180, headers=None, **kw):
        seen.update(url=url, model=body["model"])
        usage = {"prompt_tokens": 50, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 32}}
        return {**_ok("garbled nonsense here"), "usage": usage}

    monkeypatch.setattr(bo, "_post_json", fake_post)
    argv = ["bakeoff", "--conf", conf, "--models", "vendor/m", "--openai-url", "https://api.x/v1/chat/completions"]
    argv += ["--key-env", "TEST_BAKE_KEY", "--json", str(out_json)]
    monkeypatch.setattr(bo.sys, "argv", argv)
    bo.main()
    assert seen == {"url": "https://api.x/v1/chat/completions", "model": "vendor/m"}
    row = json.loads(out_json.read_text())["vendor/m"][0]
    assert (row["prompt_tokens"], row["completion_tokens"], row["cached_tokens"]) == (50, 4, 32)
    assert _KEY not in out_json.read_text()


def test_main_rejects_openai_url_without_key_env(tmp_path, monkeypatch):
    conf = _write(tmp_path, [_conf_row()])
    monkeypatch.setattr(bo.sys, "argv", ["bakeoff", "--conf", conf, "--openai-url", "https://x/v1/chat/completions"])
    with pytest.raises(SystemExit):
        bo.main()


# --- anchored mode: --dump-refs / --refs ----------------------------------------
#
# Production's normal path is ANCHORED: repair.process hands each target the overlapping line
# of the video's embedded English subtitle track as `ref`. The media lives on another machine,
# so the bake-off is split: --dump-refs (needs the video, no model calls) writes the refs,
# --refs (needs only the conf + that file) runs the models with them.

import common as _common  # noqa: E402
import hallucination as _hallucination  # noqa: E402


def _row(text, lp, start, end, **kw):
    return {**_conf_row(text, lp=lp), "start": start, "end": end, **kw}


_ANCHOR_ROWS = [
    _row("A perfectly clear line.", -0.1, 0.0, 2.0),  # 0: not a target
    _row("grbled one", -1.4, 0.0, 2.0),  # 1: overlaps "ref A"
    _row("grbled two", -1.4, 2.5, 3.5),  # 2: overlaps nothing -> no ref
    _row("grbled three", -1.4, 4.0, 6.0),  # 3: overlaps "ref B" but its source window is bad -> ""
    _row("grbled four", -1.4, 0.0, 2.0, source_start=4.0, source_end=5.5),  # 4: ref comes from the SOURCE window
]


def _fake_media(monkeypatch):
    seen = {}

    def fake_intervals(video):
        seen["video"] = video
        return [(0.0, 2.0, "ref A"), (4.0, 6.0, "ref B")]

    monkeypatch.setattr(_common, "dialogue_intervals", fake_intervals)
    monkeypatch.setattr(_hallucination, "bad_source_window", lambda c, rec=None: c["text"] == "grbled three")
    return seen


def _dump(tmp_path, monkeypatch, limit=0, sample="spread"):
    seen = _fake_media(monkeypatch)
    conf = _write(tmp_path, _ANCHOR_ROWS)
    cards = bo.load_cards(None, conf)
    doc = bo.dump_refs(conf, cards, _glossary.load(""), "/media/ep.mkv", limit, sample)
    return doc, seen, conf


def test_dump_refs_selects_the_ref_exactly_like_repair_process(tmp_path, monkeypatch):
    doc, seen, _ = _dump(tmp_path, monkeypatch)
    assert seen["video"] == "/media/ep.mkv"
    assert doc["conf"] == "ep.dubtitles.conf.json" and doc["cards"] == 5
    got = [(t["idx"], t["text"], t["ref"], t["prev"], t["next"]) for t in doc["targets"]]
    assert got == [
        (1, "grbled one", "ref A", "A perfectly clear line.", "grbled two"),
        (2, "grbled two", "", "grbled one", "grbled three"),
        (3, "grbled three", "", "grbled two", "grbled four"),  # bad source window -> "" despite the overlap
        (4, "grbled four", "ref B", "grbled three", ""),  # source_start/end, not start/end
    ]


def test_dump_refs_limit_zero_means_all_and_a_limit_samples(tmp_path, monkeypatch):
    doc, _, _ = _dump(tmp_path, monkeypatch, limit=0)
    assert len(doc["targets"]) == 4
    doc, _, _ = _dump(tmp_path, monkeypatch, limit=2, sample="head")
    assert [t["idx"] for t in doc["targets"]] == [1, 2]


def test_dump_refs_cli_makes_no_model_calls_and_prints_counts(tmp_path, monkeypatch, capsys):
    _fake_media(monkeypatch)
    conf = _write(tmp_path, _ANCHOR_ROWS)
    out = tmp_path / "refs.json"
    monkeypatch.setattr(bo, "ask", lambda *a, **k: pytest.fail("dump-refs must not call a model"))
    monkeypatch.setattr(bo, "_post_json", lambda *a, **k: pytest.fail("no network"))
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"names": []}))
    argv = ["bakeoff", "--conf", conf, "--glossary", str(g), "--dump-refs", str(out), "--video", "/media/ep.mkv"]
    argv += ["--limit", "0"]
    monkeypatch.setattr(bo.sys, "argv", argv)
    bo.main()
    text = capsys.readouterr().out
    assert "targets=4" in text and "with_ref=2" in text and "without_ref=2" in text
    assert len(json.loads(out.read_text())["targets"]) == 4


def test_dump_refs_cli_requires_conf_and_video(tmp_path, monkeypatch):
    conf = _write(tmp_path, _ANCHOR_ROWS)
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"names": []}))
    argv = ["bakeoff", "--conf", conf, "--glossary", str(g), "--dump-refs", str(tmp_path / "r.json")]
    monkeypatch.setattr(bo.sys, "argv", argv)
    with pytest.raises(SystemExit):
        bo.main()


def _run_refs(tmp_path, monkeypatch, capsys, *extra, gloss_path=""):
    if not gloss_path:
        gloss_path = str(tmp_path / "g0.json")
        (tmp_path / "g0.json").write_text(json.dumps({"names": []}))
    doc, _, conf = _dump(tmp_path, monkeypatch)
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(doc))
    prompts = []
    monkeypatch.setattr(bo, "ask", lambda ollama, m, p, *a, **k: (prompts.append(p) or "grbled one fixed", 0.1))
    argv = ["bakeoff", "--conf", conf, "--refs", str(refs), "--models", "m1", "--glossary", gloss_path, *extra]
    monkeypatch.setattr(bo.sys, "argv", argv)
    bo.main()
    return prompts, capsys.readouterr().out


def test_refs_round_trip_builds_anchored_prompts_and_skips_unanchored(tmp_path, monkeypatch, capsys):
    prompts, out = _run_refs(tmp_path, monkeypatch, capsys)
    assert len(prompts) == 2  # idx 2 and 3 have no ref -> skipped, as production skips them
    assert "<official_subtitle_reference>ref A</official_subtitle_reference>" in prompts[0]
    assert 'Previous line (for context): "A perfectly clear line."' in prompts[0]
    assert 'Next line (for context): "grbled two"' in prompts[0]
    assert "<official_subtitle_reference>ref B</official_subtitle_reference>" in prompts[1]
    assert "2 target(s) skipped" in out and "no fansub reference" in out


def test_include_unanchored_keeps_the_ref_less_targets(tmp_path, monkeypatch, capsys):
    prompts, _ = _run_refs(tmp_path, monkeypatch, capsys, "--include-unanchored")
    assert len(prompts) == 4
    assert "<official_subtitle_reference>" not in prompts[1]


def test_a_glossary_declaring_unanchored_repair_keeps_them_without_the_flag(tmp_path, monkeypatch, capsys):
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"names": [], "unanchored_repair": True}))
    prompts, _ = _run_refs(tmp_path, monkeypatch, capsys, gloss_path=str(g))
    assert len(prompts) == 4


def test_refs_that_do_not_match_the_conf_fail_loudly(tmp_path, monkeypatch):
    doc, _, conf = _dump(tmp_path, monkeypatch)
    doc["targets"][1]["text"] = "something else entirely"
    cards = bo.load_cards(None, conf)
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(doc))
    with pytest.raises(SystemExit) as e:
        bo.load_refs(str(refs), cards, conf)
    msg = str(e.value)
    assert "idx 2" in msg and "something else entirely" in msg and "grbled two" in msg


def test_refs_idx_out_of_range_fails_loudly(tmp_path, monkeypatch):
    doc, _, conf = _dump(tmp_path, monkeypatch)
    doc["targets"][0]["idx"] = 99
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(doc))
    with pytest.raises(SystemExit):
        bo.load_refs(str(refs), bo.load_cards(None, conf), conf)


def test_score_model_hands_each_targets_own_ref_to_accept_repair(monkeypatch):
    seen = []
    monkeypatch.setattr(_repair, "accept_repair", lambda orig, new, ref, dur, gloss: seen.append(ref) or True)
    ts = [
        {"text": "grbled one", "start": 0, "end": 2, "_ref": "REF-1"},
        {"text": "grbled two", "start": 0, "end": 2, "_ref": "REF-2"},
    ]
    bo.score_model("m", ts, ["grabled one", "grabled two"], 1.0, _glossary.load(""))
    assert seen == ["REF-1", "REF-2"]


def test_score_model_single_ref_signature_still_works(monkeypatch):
    seen = []
    monkeypatch.setattr(_repair, "accept_repair", lambda orig, new, ref, dur, gloss: seen.append(ref) or True)
    ts = [{"text": "grbled one", "start": 0, "end": 2}]
    bo.score_model("m", ts, ["grabled one"], 1.0, _glossary.load(""), ref="SHARED")
    assert seen == ["SHARED"]


def test_ref_borrow_counts_outputs_that_import_words_from_the_fansub():
    ts = [
        {"text": "he drew his sword", "start": 0, "end": 3, "_ref": "He drew his blade swiftly."},
        {"text": "he drew his sword", "start": 0, "end": 3, "_ref": "He drew his blade swiftly."},
        {"text": "he drew his sword", "start": 0, "end": 3, "_ref": "Unrelated words entirely."},
    ]
    outs = ["he drew his blade swiftly", "he drew his sword now", "he drew his sword"]
    s = bo.score_model("m", ts, outs, 1.0, _glossary.load(""))
    assert s["ref_borrow"] == 1  # only the first copies reference words that were not in the ASR line
    assert s["anchored"] is True
    table = bo.format_summary(bo.rank_models([s]))
    assert "borrow" in table
    glossary_only = bo.score_model("m", [{"text": "a b", "start": 0, "end": 2}], ["a c"], 1.0, _glossary.load(""))
    assert glossary_only["anchored"] is False and "borrow" not in bo.format_summary(bo.rank_models([glossary_only]))


def test_json_rows_are_admitted_with_each_targets_own_ref(tmp_path, monkeypatch, capsys):
    """format_comparison rebuilds the side-by-side from these rows, so their `admitted` must
    be the same verdict the summary's ship column uses -- computed against the same ref."""
    seen = []
    real = _repair.accept_repair
    monkeypatch.setattr(_repair, "accept_repair", lambda o, n, ref, d, g: seen.append((o, ref)) or real(o, n, ref, d, g))
    out_json = tmp_path / "rows.json"
    _run_refs(tmp_path, monkeypatch, capsys, "--json", str(out_json))
    rows = json.loads(out_json.read_text())["m1"]
    assert [r["ref"] for r in rows] == ["ref A", "ref B"]
    assert ("grbled one", "ref A") in seen[-2:] and ("grbled four", "ref B") in seen[-2:]
    assert seen[-2:] == [("grbled one", "ref A"), ("grbled four", "ref B")]


def test_dump_refs_requires_the_glossary(tmp_path, monkeypatch):
    """is_target consults glossary.name_suspect, so a dump cut without the glossary silently
    drops the name-suspect targets and the later --refs run cannot tell."""
    conf = _write(tmp_path, _ANCHOR_ROWS)
    argv = ["bakeoff", "--conf", conf, "--dump-refs", str(tmp_path / "r.json"), "--video", "/v.mkv"]
    monkeypatch.setattr(bo.sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        bo.main()
    assert "--glossary" in str(e.value)


# --- review fixes: key hygiene, redirects, Retry-After, truncation ------------------

import http.server  # noqa: E402
import threading  # noqa: E402
import types  # noqa: E402


def _capture(monkeypatch, resp=None, exc=None):
    seen = {}

    def fake_post(url, body, timeout=180, headers=None, **kw):
        seen.update(url=url, body=body, headers=headers)
        if exc:
            raise exc
        return resp if resp is not None else _ok("fixed")

    monkeypatch.setattr(bo, "_post_json", fake_post)
    return seen


def test_openai_strips_a_trailing_cr_from_the_key(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY + "\r")
    seen = _capture(monkeypatch)
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")[0] == "fixed"
    assert seen["headers"]["Authorization"] == f"Bearer {_KEY}"


@pytest.mark.parametrize("bad", ["sk-abc def\nxyz", "sk-abc def", "sk-abc\x07def"])
def test_openai_key_with_spaces_or_control_characters_exits_naming_only_the_variable(monkeypatch, bad):
    monkeypatch.setenv("TEST_BAKE_KEY", bad)
    monkeypatch.setattr(bo, "_post_json", lambda *a, **k: pytest.fail("must not post"))
    with pytest.raises(SystemExit) as e:
        bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert "TEST_BAKE_KEY" in str(e.value) and "sk-abc" not in str(e.value)


def test_openai_never_builds_output_from_an_exception_that_quotes_the_header(tmp_path, monkeypatch, capsys):
    """http.client's ValueError quotes the header value; the bake-off used to write
    <ERROR {e}> into stdout AND the --json rows."""
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    _capture(monkeypatch, exc=ValueError(f"Invalid header value b'Bearer {_KEY}\\r'"))
    out, _ = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert out == "<ERROR ValueError>"
    conf = _write(tmp_path, [_conf_row("grbled nnsense here", lp=-1.4, nsp=0.02)])
    out_json = tmp_path / "r.json"
    argv = ["bakeoff", "--conf", conf, "--models", "m", "--openai-url", "https://x/v1/chat/completions"]
    monkeypatch.setattr(bo.sys, "argv", argv + ["--key-env", "TEST_BAKE_KEY", "--json", str(out_json)])
    bo.main()
    cap = capsys.readouterr()
    assert _KEY not in cap.out + cap.err + out_json.read_text() and "sk-bakeoff" not in cap.out + out_json.read_text()


def test_openai_http_error_reports_only_the_status(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    _capture(monkeypatch, exc=_http_error(401))
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")[0] == "<ERROR HTTP 401>"


def test_openai_truncated_empty_reply_is_an_error_not_an_empty(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    resp = {"choices": [{"message": {"content": "", "reasoning_content": "hmm"}, "finish_reason": "length"}]}
    _capture(monkeypatch, resp=resp)
    out, _ = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert out == "<ERROR truncated (finish_reason=length)>"
    s = bo.score_model("m", [{"text": "x", "start": 0, "end": 2}], [out], 1.0, _glossary.load(""))
    assert s["errors"] == 1 and s["empties"] == 0 and s["inert"] == 0


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen = []

    def _record(self):
        type(self).seen.append(self.headers.get("Authorization"))
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"content":"x"}}]}')

    do_POST = do_GET = _record  # urllib turns a redirected POST into a GET

    def log_message(self, *a):
        pass


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_openai_does_not_follow_a_redirect_and_never_forwards_the_key(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    _Recorder.seen = []
    target = _serve(_Recorder)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/v1/chat/completions")
            self.end_headers()

        def log_message(self, *a):
            pass

    first = _serve(Redirector)
    try:
        out, _ = bo.ask_openai(f"http://127.0.0.1:{first.server_port}/x", "m", "P", "TEST_BAKE_KEY")
    finally:
        first.shutdown()
        target.shutdown()
    assert out == "<ERROR HTTP 302 redirect refused>"
    assert _Recorder.seen == []  # the second server received nothing at all


@pytest.mark.parametrize("raw", ["nan", "inf", "-3", "Wed, 21 Oct 2026 07:28:00 GMT", "soon", "3600", "60.5"])
def test_openai_retry_after_outside_0_to_60_or_not_a_number_falls_back_to_5s(monkeypatch, raw):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    slept = []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        raise _http_error(429, raw)

    monkeypatch.setattr(bo, "_post_json", fake_post)
    monkeypatch.setattr(bo.time, "sleep", slept.append)
    out, _ = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")  # must not raise
    assert slept == [5.0] and "rate-limited" in out


def test_openai_a_valid_retry_after_is_honoured(monkeypatch):
    """GUARD: passes on the old code (7 s was already honoured)."""
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    slept = []
    calls = []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(429, "7")
        return _ok("ok")

    monkeypatch.setattr(bo, "_post_json", fake_post)
    monkeypatch.setattr(bo.time, "sleep", slept.append)
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")[0] == "ok" and slept == [7.0]


@pytest.mark.parametrize("usage", [[1], "x", {"prompt_tokens_details": [1]}, {"prompt_tokens_details": "x", "prompt_tokens": 3}])
def test_openai_odd_usage_never_discards_a_valid_reply(monkeypatch, usage):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    _capture(monkeypatch, resp={**_ok("fine"), "usage": usage})
    sink = []
    assert bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY", usage_sink=sink)[0] == "fine"
    assert len(sink) == 1


def test_openai_url_without_explicit_models_exits(tmp_path, monkeypatch):
    conf = _write(tmp_path, [_conf_row()])
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    argv = ["bakeoff", "--conf", conf, "--openai-url", "https://x/v1/chat/completions", "--key-env", "TEST_BAKE_KEY"]
    monkeypatch.setattr(bo.sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        bo.main()
    assert "--models" in str(e.value)


def test_max_tokens_flag_and_env_default(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    monkeypatch.setenv("REPAIR_MAX_TOKENS", "333")
    conf = _write(tmp_path, [_conf_row("grbled nnsense here", lp=-1.4, nsp=0.02)])
    bodies = []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        bodies.append(b["max_tokens"])
        return _ok("x")

    monkeypatch.setattr(bo, "_post_json", fake_post)
    base = ["bakeoff", "--conf", conf, "--models", "m", "--openai-url", "https://x/c", "--key-env", "TEST_BAKE_KEY"]
    monkeypatch.setattr(bo.sys, "argv", base)
    bo.main()
    monkeypatch.setattr(bo.sys, "argv", base + ["--max-tokens", "77"])
    bo.main()
    assert bodies == [333, 77]


def test_openai_latency_excludes_the_retry_after_sleep(monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    clock = [0.0]
    fake_time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    calls = []

    def fake_post(u, b, timeout=180, headers=None, **kw):
        calls.append(1)
        clock[0] += 2.0  # each attempt takes 2 s
        if len(calls) == 1:
            raise _http_error(429, "30")
        return _ok("ok")

    monkeypatch.setattr(bo, "_post_json", fake_post)
    monkeypatch.setattr(bo, "time", fake_time)
    _, dt = bo.ask_openai("u", "m", "P", "TEST_BAKE_KEY")
    assert dt == 2.0  # not 34.0


# --- anchored mode review fixes: raw conf text, output correction, validation, differential --------

import repair as _prod  # noqa: E402


def _gfile(tmp_path, data=None, name="g.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data if data is not None else {"names": []}))
    return str(p)


def _doc_and_cards(tmp_path, monkeypatch):
    doc, _, conf = _dump(tmp_path, monkeypatch)
    return doc, bo.load_cards(None, conf), conf


def _expect_exit(tmp_path, doc, cards, conf, *needles, **kw):
    refs = tmp_path / "refs2.json"
    refs.write_text(json.dumps(doc))
    with pytest.raises(SystemExit) as e:
        bo.load_refs(str(refs), cards, conf, **kw)
    for n in needles:
        assert n in str(e.value), (n, str(e.value))


def test_dump_refs_without_conf_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(bo.sys, "argv", ["bakeoff", "--dump-refs", str(tmp_path / "r.json"), "--video", "v", "--glossary", "g"])
    with pytest.raises(SystemExit) as e:
        bo.main()
    assert "--conf" in str(e.value)


def test_refs_without_glossary_exits(tmp_path, monkeypatch):
    doc, _, conf = _doc_and_cards(tmp_path, monkeypatch)
    (tmp_path / "refs.json").write_text(json.dumps(doc))
    monkeypatch.setattr(bo.sys, "argv", ["bakeoff", "--conf", conf, "--refs", str(tmp_path / "refs.json"), "--models", "m"])
    with pytest.raises(SystemExit) as e:
        bo.main()
    assert "--glossary" in str(e.value)


def test_duplicate_idx_in_a_refs_file_exits(tmp_path, monkeypatch):
    doc, cards, conf = _doc_and_cards(tmp_path, monkeypatch)
    doc["targets"].append(dict(doc["targets"][0]))
    _expect_exit(tmp_path, doc, cards, conf, "duplicate", "idx 1")


@pytest.mark.parametrize("bad", [True, "1", 1.0, None, -1])
def test_a_non_integer_or_negative_idx_exits(tmp_path, monkeypatch, bad):
    doc, cards, conf = _doc_and_cards(tmp_path, monkeypatch)
    doc["targets"][0]["idx"] = bad
    _expect_exit(tmp_path, doc, cards, conf, "idx")


def test_a_target_without_text_exits_cleanly(tmp_path, monkeypatch):
    doc, cards, conf = _doc_and_cards(tmp_path, monkeypatch)
    del doc["targets"][0]["text"]
    _expect_exit(tmp_path, doc, cards, conf, "text")


def test_a_refs_file_cut_from_a_different_conf_exits_unless_allowed(tmp_path, monkeypatch):
    doc, cards, conf = _doc_and_cards(tmp_path, monkeypatch)
    doc["conf"] = "other.dubtitles.conf.json"
    _expect_exit(tmp_path, doc, cards, conf, "other.dubtitles.conf.json", "--allow-conf-mismatch")
    (tmp_path / "ok.json").write_text(json.dumps(doc))
    assert bo.load_refs(str(tmp_path / "ok.json"), cards, conf, allow_conf_mismatch=True)


def test_a_conf_with_extra_cards_since_the_dump_exits(tmp_path, monkeypatch):
    doc, cards, conf = _doc_and_cards(tmp_path, monkeypatch)
    doc["cards"] = len(cards) - 1
    _expect_exit(tmp_path, doc, cards, conf, "cards")


def test_a_retimed_card_since_the_dump_exits(tmp_path, monkeypatch):
    doc, cards, conf = _doc_and_cards(tmp_path, monkeypatch)
    cards[1]["start"] += 0.5
    _expect_exit(tmp_path, doc, cards, conf, "idx 1", "retimed")


def test_dump_takes_text_from_the_raw_conf_rows_not_the_glossary_corrected_ones(tmp_path, monkeypatch):
    """repair.process never re-runs glossary.correct on conf text, so neither may the dump."""
    _fake_media(monkeypatch)
    rows = [_row("Zorro drew his blade", -1.4, 0.0, 2.0)]
    conf = _write(tmp_path, rows)
    g = _glossary.load_dict({"names": ["Zoro"], "hard_fixes": {"Zorro": "Zoro"}})
    assert _glossary.correct("Zorro drew his blade", g)[0] != "Zorro drew his blade", "fixture must change the line"
    doc = bo.dump_refs(conf, bo.load_cards(None, conf), g, "/v.mkv", 0, "spread")
    assert doc["targets"][0]["text"] == "Zorro drew his blade"


def test_score_model_applies_the_glossary_to_the_output_before_the_gate(monkeypatch):
    """repair.py runs glossary.correct on the model's reply before accept_repair."""
    g = _glossary.load_dict({"names": ["Zoro"], "hard_fixes": {"Zorro": "Zoro"}})
    seen = []
    monkeypatch.setattr(_repair, "accept_repair", lambda o, n, ref, d, gl: seen.append(n) or True)
    bo.score_model("m", [{"text": "Zoro drew his sword", "start": 0, "end": 3}], ["Zorro drew his blade"], 1.0, g)
    assert seen == ["Zoro drew his blade"]


def test_json_rows_gate_the_corrected_output_too(tmp_path, monkeypatch):
    conf = _write(tmp_path, [_row("grbled nnsense here", -1.4, 0.0, 3.0)])
    g = _gfile(tmp_path, {"names": ["Zoro"], "hard_fixes": {"Zorro": "Zoro"}})
    seen = []
    monkeypatch.setattr(_repair, "accept_repair", lambda o, n, ref, d, gl: seen.append(n) or True)
    monkeypatch.setattr(bo, "ask", lambda *a, **k: ("Zorro drew his blade", 0.1))
    out_json = tmp_path / "rows.json"
    monkeypatch.setattr(bo.sys, "argv", ["bakeoff", "--conf", conf, "--glossary", g, "--models", "m", "--json", str(out_json)])
    bo.main()
    assert seen and set(seen) == {"Zoro drew his blade"}


def _differential(tmp_path, monkeypatch, capsys, arc=None):
    """Run the REAL repair.process and the bake-off over the same conf; return both prompt lists."""
    stem = str(tmp_path / "Show S01E02")
    conf_path = stem + _prod.CONF_SUFFIX
    rows = [
        _row("A perfectly clear line.", -0.1, 0.0, 2.0),
        _row("Zorro drew his blade", -1.4, 0.0, 2.0),  # raw conf text predates the glossary fix
        _row("grbled two", -1.4, 2.5, 3.5),  # no fansub line -> production skips it
        _row("he saw spondum there", -1.4, 4.0, 6.0, source_start=4.0, source_end=5.5),
    ]
    open(stem + _prod.SRT_SUFFIX, "w").close()
    open(conf_path, "w").write(json.dumps(rows))
    gdata = {
        "names": ["Zoro", "Spandam"],
        "hard_fixes": {"Zorro": "Zoro"},
        "episode_tags": {"spandam": ["S01E02"]},  # reorders the prompt's term list for THIS episode
        "arc_tags": {"zoro": ["Other"]},
    }
    gpath = _gfile(tmp_path, gdata)
    gloss = _glossary.load(gpath)
    video = stem + ".mkv"
    ivals = [(0.0, 2.0, "Zoro drew his blade."), (4.0, 6.0, "He saw Spandam there.")]
    monkeypatch.setattr(_prod, "find_video", lambda s: video)
    monkeypatch.setattr(_prod, "glossary_for", lambda v: gloss)
    monkeypatch.setattr(_prod, "dialogue_intervals", lambda v: ivals)
    monkeypatch.setattr(_common, "dialogue_intervals", lambda v: ivals)
    monkeypatch.setattr(_glossary, "arc_for", lambda v: arc)
    prod_prompts = []
    monkeypatch.setattr(_prod, "llm", lambda prompt, model=None: prod_prompts.append(prompt) or "")
    _prod.process(conf_path)
    capsys.readouterr()

    refs = tmp_path / "refs.json"
    argv = ["bakeoff", "--conf", conf_path, "--glossary", gpath, "--dump-refs", str(refs), "--video", video, "--limit", "0"]
    monkeypatch.setattr(bo.sys, "argv", argv)
    bo.main()
    bake_prompts = []
    monkeypatch.setattr(bo, "ask", lambda o, m, p, *a, **k: bake_prompts.append(p) or ("x", 0.1))
    argv = ["bakeoff", "--conf", conf_path, "--glossary", gpath, "--refs", str(refs), "--models", "m"]
    monkeypatch.setattr(bo.sys, "argv", argv)
    bo.main()
    return prod_prompts, bake_prompts


def test_differential_bakeoff_prompts_equal_the_prompts_repair_process_builds(tmp_path, monkeypatch, capsys):
    prod, bake = _differential(tmp_path, monkeypatch, capsys)
    assert len(prod) == 2  # the clear line is not a target; "grbled two" has no ref and is skipped
    assert any("ASR line: Zorro drew his blade" in p for p in prod), "the raw conf text is what production sends"
    assert bake == prod
    assert "Spandam, Zoro" in prod[0], "the episode tier must be live, or this test cannot see a dropped episode"


def test_differential_with_an_arc_matches_too(tmp_path, monkeypatch, capsys):
    """Arc and episode weighting reorder the glossary terms in the prompt."""
    prod, bake = _differential(tmp_path, monkeypatch, capsys, arc="Dressrosa")
    assert prod and bake == prod


# --- review round 3: safe env default, source window, glossary fingerprint ---------------


def test_a_bad_repair_max_tokens_env_falls_back_to_1024_in_the_bakeoff(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BAKE_KEY", _KEY)
    monkeypatch.setenv("REPAIR_MAX_TOKENS", "1k")
    conf = _write(tmp_path, [_conf_row("grbled nnsense here", lp=-1.4, nsp=0.02)])
    bodies = []
    monkeypatch.setattr(
        bo, "_post_json", lambda u, b, timeout=180, headers=None, **kw: bodies.append(b["max_tokens"]) or _ok("x")
    )
    argv = ["bakeoff", "--conf", conf, "--models", "m", "--openai-url", "https://x/c", "--key-env", "TEST_BAKE_KEY"]
    monkeypatch.setattr(bo.sys, "argv", argv)
    bo.main()
    assert bodies == [1024]


def test_a_moved_source_window_since_the_dump_exits(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    conf = _write(tmp_path, _ANCHOR_ROWS)
    cards = bo.load_cards(None, conf)
    doc = bo.dump_refs(conf, cards, _glossary.load(""), "/v.mkv", 0, "spread")
    assert [t["source_start"] for t in doc["targets"]] == [None, None, None, 4.0]
    cards[4]["source_start"] = 0.0  # the window moved, so the dumped ref no longer belongs to it
    _expect_exit(tmp_path, doc, cards, conf, "idx 4", "source_start")


def test_the_dump_records_a_glossary_fingerprint_and_refs_exits_when_it_differs(tmp_path, monkeypatch):
    import hashlib

    _fake_media(monkeypatch)
    conf = _write(tmp_path, _ANCHOR_ROWS)
    g1 = _gfile(tmp_path, {"names": ["Alpha"]}, "g1.json")
    g2 = _gfile(tmp_path, {"names": ["Beta"]}, "g2.json")
    cards = bo.load_cards(None, conf)
    doc = bo.dump_refs(conf, cards, _glossary.load(g1), "/v.mkv", 0, "spread", glossary_path=g1)
    assert doc["glossary_sha256"] == hashlib.sha256(open(g1, "rb").read()).hexdigest()
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(doc))
    assert bo.load_refs(str(refs), cards, conf, glossary_path=g1)  # same glossary: fine
    with pytest.raises(SystemExit) as e:
        bo.load_refs(str(refs), cards, conf, glossary_path=g2)
    msg = str(e.value)
    assert doc["glossary_sha256"][:12] in msg and hashlib.sha256(open(g2, "rb").read()).hexdigest()[:12] in msg
    assert bo.load_refs(str(refs), cards, conf, glossary_path=g2, allow_glossary_mismatch=True)


def test_main_threads_the_glossary_path_into_dump_and_refs(tmp_path, monkeypatch, capsys):
    _fake_media(monkeypatch)
    conf = _write(tmp_path, _ANCHOR_ROWS)
    g1 = _gfile(tmp_path, {"names": []}, "g1.json")
    g2 = _gfile(tmp_path, {"names": ["Other"]}, "g2.json")
    refs = tmp_path / "r.json"
    monkeypatch.setattr(bo.sys, "argv", ["bakeoff", "--conf", conf, "--glossary", g1, "--dump-refs", str(refs), "--video", "v"])
    bo.main()
    monkeypatch.setattr(bo, "ask", lambda *a, **k: ("x", 0.1))
    run = ["bakeoff", "--conf", conf, "--glossary", g2, "--refs", str(refs), "--models", "m"]
    monkeypatch.setattr(bo.sys, "argv", run)
    with pytest.raises(SystemExit):
        bo.main()
    monkeypatch.setattr(bo.sys, "argv", run + ["--allow-glossary-mismatch"])
    bo.main()
