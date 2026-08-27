"""Checks for tools/model_bakeoff.py's report shaping.

The transcription half needs CUDA and is exercised on the box. What is tested here is
the part that decides the outcome: whether a model's no_speech_prob distribution is ALIVE
or collapsed. §5.3 of the VAD design measured large-v3-turbo pinning nsp at ~1e-10 on
every card, which makes the `music` drop rule and the `maybe_silence` flag structurally
inert -- 2 of the gate's 5 rules unable to fire. Getting this summary wrong would hide
exactly that.
"""

from tools import model_bakeoff as mb


def test_a_collapsed_decoder_reports_no_live_nsp():
    """turbo's measured behaviour: every segment pinned at ~1e-10."""
    nsps = [1e-10, 2e-10, 1.5e-10, 9e-11]
    out = mb.summarise(nsps, [-0.3, -0.4, -0.2, -0.5], ["a", "b", "c", "d"])
    assert out["nsp_alive_frac"] == 0.0
    assert out["nsp_over_0_5"] == 0
    assert out["nsp_over_0_95"] == 0


def test_a_live_decoder_reports_a_real_distribution():
    nsps = [0.01, 0.4, 0.7, 0.97]
    out = mb.summarise(nsps, [-0.3, -0.4, -0.2, -0.5], ["a", "b", "c", "d"])
    assert out["nsp_alive_frac"] == 1.0
    assert out["nsp_over_0_5"] == 2
    assert out["nsp_over_0_95"] == 1


def test_blocklist_hits_use_the_pipelines_own_rule():
    """The two models are judged by the gate's own standard, not a bespoke one."""
    out = mb.summarise([0.1], [-0.3], ["To be continued...", "a real line"])
    assert out["blocklist_hits"] >= 1


def test_an_empty_run_summarises_without_raising():
    """A model that loaded but transcribed nothing must still produce a report."""
    out = mb.summarise([], [], [])
    assert out["segments"] == 0
    assert out["nsp_alive_frac"] is None


def test_a_live_nsp_alone_does_not_revive_the_music_rule():
    """The decisive check. hallucination.music is a CONJUNCTION: nsp > 0.95 AND
    avg_logprob < -2.0. A model can have a perfectly live nsp distribution and still
    never fire it, if the high-nsp segments are not the same segments with terrible
    logprob. Reporting the two marginals separately would imply a revival that does not
    exist -- which is the shape of every wrong conclusion this project has had to retract."""
    nsps = [0.99, 0.98, 0.10]  # two segments clear the nsp threshold
    lps = [-0.3, -0.4, -3.0]  # ...but neither of those has a bad logprob
    out = mb.summarise(nsps, lps, ["a", "b", "c"])
    assert out["nsp_over_0_95"] == 2
    assert out["music_rule_would_fire"] == 0


def test_the_conjunction_fires_when_both_conditions_land_together():
    out = mb.summarise([0.99, 0.10], [-3.0, -0.2], ["a", "b"])
    assert out["music_rule_would_fire"] == 1


def test_maybe_silence_uses_the_gates_own_threshold():
    out = mb.summarise([0.9, 0.4, 0.6], [-0.2, -0.2, -0.2], ["a", "b", "c"])
    assert out["maybe_silence_would_fire"] == 2
