"""Per-stage unresolved queue -- the missing human rung of the deterministic -> LLM -> human
ladder for the subtitle path (glossary_acquire already has one; repair/punctuation did not)."""

import os
import stat

import unresolved


def test_records_per_stage_and_survives_reread(tmp_path):
    stem = str(tmp_path / "ep")
    assert (
        unresolved.record(
            stem, "repair", "no_reference", original_text="Gum -gum!", source_start=1.0, source_end=1.4, avg_logprob=-0.79
        )
        is True
    )
    assert unresolved.record(stem, "punctuation", "llm_empty", original_text="who are you") is True
    got = unresolved.items(stem)
    assert [e["stage"] for e in got] == ["repair", "punctuation"]
    assert got[0]["reason"] == "no_reference"
    assert got[0]["original_text"] == "Gum -gum!"
    assert got[0]["source_start"] == 1.0


def test_rejected_guard_keeps_the_model_proposal(tmp_path):
    """repair.py currently increments `rejected` and DISCARDS what the model proposed. The
    proposal is the whole evidence a human needs to judge whether the guard was right."""
    stem = str(tmp_path / "ep")
    unresolved.record(
        stem, "repair", "rejected_guard", original_text="catch Hirohoshi", proposed_text="catch Crocodile", avg_logprob=-1.2
    )
    e = unresolved.items(stem)[0]
    assert e["original_text"] == "catch Hirohoshi"
    assert e["proposed_text"] == "catch Crocodile"


def test_never_raises_and_never_blocks_an_episode(tmp_path):
    """Same contract as qc.write: this is observability. It must not fail an episode that
    otherwise generated correctly."""
    assert unresolved.record("/nonexistent/dir/ep", "repair", "no_reference") is False
    assert unresolved.items("/nonexistent/dir/ep") == []


def test_sidecar_is_group_writable(tmp_path):
    """A non-root writer must be able to append later -- see common.SIDECAR_MODE."""
    import common

    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference")
    mode = stat.S_IMODE(os.stat(stem + unresolved.SUFFIX).st_mode)
    assert mode == common.SIDECAR_MODE


def test_append_is_o1_and_readable_at_every_step(tmp_path):
    """JSONL: one entry per line, appended. The array version re-read and re-wrote the whole
    file per card -- O(n^2) I/O on a path that fires ~86x per episode, one CIFS round-trip
    each. The file must still parse after every append."""
    stem = str(tmp_path / "ep")
    for i in range(5):
        unresolved.record(stem, "repair", "no_reference", original_text=f"line {i}")
        assert len(unresolved.items(stem)) == i + 1


def test_torn_final_line_costs_only_that_entry(tmp_path):
    """The one failure an append can produce. Everything before it must survive."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="intact")
    with open(stem + unresolved.SUFFIX, "a") as f:
        f.write('{"stage": "repair", "reas')  # torn mid-write
    got = unresolved.items(stem)
    assert len(got) == 1 and got[0]["original_text"] == "intact"


def test_resolve_marks_without_deleting_evidence(tmp_path):
    """A reviewed entry keeps its evidence -- the queue is the audit trail, not a worklist
    that shrinks. Mirrors glossary_acquire.record_decision."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="Gum -gum!")
    assert unresolved.resolve(stem, 0, accept=True, note="fansub missing, text is fine") is True
    e = unresolved.items(stem)[0]
    assert e["resolved"] is True
    assert e["note"] == "fansub missing, text is fine"
    assert e["original_text"] == "Gum -gum!"
    assert unresolved.pending(stem) == []


def test_pending_is_what_review_shows(tmp_path):
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="a")
    unresolved.record(stem, "punctuation", "llm_empty", original_text="b")
    unresolved.resolve(stem, 0, accept=True)
    assert [e["original_text"] for e in unresolved.pending(stem)] == ["b"]


def test_repair_llm_empty_is_a_declared_reason(tmp_path):
    """A repair call that times out returns "" -- it fails accept_repair, but the
    `if new and ...` guard is falsy so nothing was incremented and nothing recorded. That
    is the silent-fallback class this module exists to remove, and it survived inside the
    fix for it until an end-to-end run against a dead endpoint exposed it."""
    assert "llm_empty" in unresolved.REASONS["repair"]
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "llm_empty", original_text="garbled line", reference="the fansub line", avg_logprob=-1.4)
    e = unresolved.items(stem)[0]
    assert e["reason"] == "llm_empty" and e["reference"] == "the fansub line"


def test_repair_applied_is_a_known_stage_with_its_own_evidence(tmp_path):
    """Breaks if the accepted-repair stage is missing from REASONS, or is rendered without
    the two texts a reviewer compares.

    REASONS exists so "the --review CLI and the call sites cannot drift apart, and so a
    typo'd reason is visible rather than silently creating a new bucket"
    (unresolved.py:45). A stage recorded but not declared is exactly that silent bucket."""
    assert "accepted" in unresolved.REASONS["repair_applied"]
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair_applied", "accepted", original_text="my fellow Samadai", proposed_text="my fellow Samurai.")
    rendered = unresolved._render(0, unresolved.items(stem)[0])
    assert "my fellow Samadai" in rendered and "my fellow Samurai." in rendered


def test_the_primary_filter_returns_only_the_judgement_worthy_reasons(tmp_path):
    """Breaks if the primary filter stops excluding the non-actionable reasons.

    Asserted on ABSENCE. pending() applies no stage filter of its own
    (unresolved.py:89), so a filter that returned everything would satisfy any
    presence-only assertion while burying the owner: ~25 judgement-worthy entries per
    episode against ~86 recorded. no_reference is mostly "this release has no fansub" --
    true, and not actionable line by line."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair_applied", "accepted", original_text="a", proposed_text="b")
    unresolved.record(stem, "repair", "rejected_guard", original_text="c", proposed_text="d")
    unresolved.record(stem, "repair", "rejected_name_invented", original_text="e", proposed_text="f")
    unresolved.record(stem, "repair", "no_reference", original_text="g")
    unresolved.record(stem, "repair", "llm_empty", original_text="h")
    unresolved.record(stem, "punctuation", "llm_empty", original_text="i")
    # REASONS["punctuation"] also carries "rejected_guard", so a filter keyed on the reason
    # alone would sweep this in. The stage is half the identity.
    unresolved.record(stem, "punctuation", "rejected_guard", original_text="j", proposed_text="k")

    primary = unresolved.pending(stem, primary_only=True)
    assert {(e["stage"], e["reason"]) for e in primary} == {
        ("repair_applied", "accepted"),
        ("repair", "rejected_guard"),
        ("repair", "rejected_name_invented"),
    }
    assert not any(e["reason"] in ("no_reference", "llm_empty") for e in primary)
    # Excluded by SCOPE, not because it cannot be judged: punctuation records both texts
    # too. If the owner widens PRIMARY, this line is the one to change -- deliberately, not
    # by discovering it broke.
    assert not any(e["stage"] == "punctuation" for e in primary)
    assert len(unresolved.pending(stem)) == 7, "the unfiltered walk must still return everything"


# --- [F-1] a CLI verdict must reach the decision store -----------------------
# `resolve()` sets a flag and writes nothing durable. repair.py suppresses re-application
# only on a stored VERDICT, so a "needs fixing" answered here was dropped in silence while
# the audit trail recorded that a human had judged the line.


def _queued(tmp_path, name, stage, reason, orig, proposed):
    import unresolved as u

    stem = str(tmp_path / name)
    u.record(stem, stage, reason, original_text=orig, proposed_text=proposed)
    return stem


def _answers(monkeypatch, *replies):
    """Drive the interactive walk: one reply per input() call, then EOF."""
    it = iter(replies)

    def fake_input(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None  # the walk ends the way a real Ctrl-D ends it

    monkeypatch.setattr("builtins.input", fake_input)


def test_needs_fixing_on_an_applied_repair_records_a_reject(tmp_path, monkeypatch):
    """The card currently shows the REPAIR, so "needs fixing" means the repair is wrong.

    Without this the answer set a flag, repair.py re-applied the same repair on the next
    run, and the re-queue suppression kept it out of the queue -- so the reviewer's
    judgement was invisible to the pipeline AND to the reviewer."""
    import decisions
    import unresolved as u

    stem = _queued(tmp_path, "ep_f", "repair_applied", "accepted", "I saw spondum", "I saw Spandam")
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(u, "show_for", lambda p: "Show")
    _answers(monkeypatch, "f", "a regression")

    u.main([stem, "--review"])

    hit = decisions.lookup(decisions.load("Show", str(tmp_path)), "I saw spondum", "I saw Spandam")
    assert hit is not None, "the verdict must be durable, not just a flag on the queue entry"
    assert hit["verdict"] == "reject"
    assert u.items(stem)[0]["resolved"] is True, "and the entry still leaves the queue"


def test_keep_as_is_and_needs_fixing_are_distinguishable_in_the_store(tmp_path, monkeypatch):
    """Both answers currently produce an identical queue state apart from one boolean, and
    neither reaches the store at all. If only one of them recorded a verdict the CLI would
    still be lossy, so this asserts the PAIR."""
    import decisions
    import unresolved as u

    stem = str(tmp_path / "ep_both")
    u.record(stem, "repair_applied", "accepted", original_text="line one", proposed_text="fix one")
    u.record(stem, "repair_applied", "accepted", original_text="line two", proposed_text="fix two")
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(u, "show_for", lambda p: "Show")
    _answers(monkeypatch, "k", "", "f", "")

    u.main([stem, "--review"])

    store = decisions.load("Show", str(tmp_path))
    one, two = decisions.lookup(store, "line one", "fix one"), decisions.lookup(store, "line two", "fix two")
    assert one is not None and two is not None, "both answers must reach the store, or the CLI is still lossy"
    assert one["verdict"] == "accept"
    assert two["verdict"] == "reject"


def test_needs_fixing_on_a_refused_repair_records_a_force(tmp_path, monkeypatch):
    """The mapping is per STAGE, because "keep as-is" is about the CARD, not the proposal.

    On a `rejected_guard` entry the card shows the ASR text -- the repair was refused -- so
    "keep as-is" endorses that refusal (a `reject` of the proposal) and "needs fixing" says
    the ASR is wrong and the refused proposal should stand, which is exactly `force`.
    Recording `reject` for both stages would silently invert the reviewer's meaning here."""
    import decisions
    import unresolved as u

    stem = _queued(tmp_path, "ep_guard", "repair", "rejected_guard", "asr text", "model text")
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(u, "show_for", lambda p: "Show")
    _answers(monkeypatch, "f", "")

    u.main([stem, "--review"])

    hit = decisions.lookup(decisions.load("Show", str(tmp_path)), "asr text", "model text")
    assert hit is not None and hit["verdict"] == "force"


def test_a_store_write_failure_is_reported_not_swallowed(tmp_path, monkeypatch, capsys):
    """A review that silently discards the human's decision is worse than one that errors,
    because the human believes the line is settled. The queue entry must NOT be marked
    resolved either -- that would hide the unsaved verdict from the next walk."""
    import decisions
    import unresolved as u

    stem = _queued(tmp_path, "ep_fail", "repair_applied", "accepted", "orig", "prop")
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(u, "show_for", lambda p: "Show")
    monkeypatch.setattr(decisions, "save", lambda *a, **k: False)
    _answers(monkeypatch, "f", "")

    u.main([stem, "--review"])

    assert "not saved" in capsys.readouterr().out.lower()
    assert u.items(stem)[0].get("resolved") is False, "an unsaved verdict must stay in the queue"
