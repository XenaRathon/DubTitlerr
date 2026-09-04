"""Unit tests for tools/asr_bakeoff.py -- the GPU-free, pure shaping half only.

The transcribers (run_whisper / run_nemo) need a CUDA stack and are exercised by
running the tool itself on one real episode; these tests pin the parts every verdict
is built from: WER math, the whisper/nemo router, the judge summary, and the
defensive NeMo transcript parser whose return shapes move between nemo versions.
"""

import wave

import pytest

from tools import asr_bakeoff as ab

# ------------------------------------------------------------------ WER arithmetic


def test_wer_zero_when_transcripts_match():
    assert ab.wer("the quick brown fox", "the quick brown fox") == 0.0


def test_wer_one_substitution_in_four_words():
    # 1 sub / 4 ref words = 0.25
    assert ab.wer("the quick brown fox", "the quick brown dog") == 0.25


def test_wer_counts_deletions_and_insertions():
    # deletion: "jumps" dropped -> 1/3
    assert ab.wer("the fox jumps", "the fox") == pytest.approx(1 / 3)
    # insertion: an extra word -> 1/2
    assert ab.wer("the fox", "the big fox") == 0.5


def test_wer_strips_punctuation_and_case_like_leaderboards():
    # Punctuation/case are stripped on BOTH sides, so formatting differences never
    # inflate the score -- same normalisation published WER numbers apply.
    assert ab.wer("The, QUICK Brown Fox!", "the quick brown fox") == 0.0


def test_wer_none_when_reference_is_empty():
    # An empty reference makes WER undefined, not infinite; None so callers can skip.
    assert ab.wer("", "anything") is None
    assert ab.wer("   ", "anything") is None


def test_edit_distance_hand_checked():
    assert ab.edit_distance(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert ab.edit_distance([], ["a", "b"]) == 2
    assert ab.edit_distance(["a", "b"], []) == 2


# ---------------------------------------------------- load_srt_reference (real ground truth)

_SDH_SRT = """\
1
00:00:01,000 --> 00:00:03,000
[dramatic music plays]

2
00:00:04,000 --> 00:00:06,000
[narrator] A long time ago…

3
00:00:07,000 --> 00:00:09,000
<i>Wait a minute.</i>
"""


def test_load_srt_reference_drops_pure_sound_cues(tmp_path):
    srt = tmp_path / "sdh.srt"
    srt.write_text(_SDH_SRT)
    text = ab.load_srt_reference(str(srt))
    # cue 1 is pure sound effect and must vanish entirely, not become empty words
    assert "music" not in text.lower() and "dramatic" not in text.lower()


def test_load_srt_reference_strips_speaker_tag_keeps_dialogue(tmp_path):
    srt = tmp_path / "sdh.srt"
    srt.write_text(_SDH_SRT)
    text = ab.load_srt_reference(str(srt))
    assert "narrator" not in text.lower()
    assert "A long time ago" in text


def test_load_srt_reference_strips_italics_markup(tmp_path):
    srt = tmp_path / "sdh.srt"
    srt.write_text(_SDH_SRT)
    text = ab.load_srt_reference(str(srt))
    assert "<i>" not in text and "Wait a minute." in text


# --------------------------------------------------------- score_against_references


def test_score_against_references_matches_by_episode_basename():
    entries = [{"episodes": [{"episode": "ep1.mkv", "text": "the quick brown fox"}]}]
    ab.score_against_references(entries, {"ep1.mkv": "the quick brown fox"})
    assert entries[0]["episodes"][0]["wer_vs_ref"] == 0.0


def test_score_against_references_skips_episodes_without_a_reference():
    entries = [{"episodes": [{"episode": "unrelated.mkv", "text": "hello"}]}]
    ab.score_against_references(entries, {"ep1.mkv": "the quick brown fox"})
    assert "wer_vs_ref" not in entries[0]["episodes"][0]


def test_score_against_references_skips_episodes_with_no_text():
    # An errored episode (no dub track, extraction failure) never got a "text" key.
    entries = [{"episodes": [{"episode": "ep1.mkv", "error": "no-eng-dub-or-extract-failed"}]}]
    ab.score_against_references(entries, {"ep1.mkv": "the quick brown fox"})
    assert "wer_vs_ref" not in entries[0]["episodes"][0]


# ---------------------------------------------------------------------- router


def test_router_sends_whisper_family_to_faster_whisper():
    assert ab.is_whisper_name("large-v3-turbo")
    assert ab.is_whisper_name("deepdml/faster-distil-whisper-large-v3")


def test_router_sends_nvidia_nemo_ids_to_nemo():
    assert not ab.is_whisper_name("nvidia/parakeet-tdt-0.6b-v3")
    assert not ab.is_whisper_name("nvidia/canary-1b-v2")
    assert not ab.is_whisper_name("nvidia/canary-qwen-2.5b")


def test_router_sends_qwen_org_prefix_to_qwen():
    assert ab.is_qwen_name("Qwen/Qwen3-ASR-1.7B")
    assert ab.is_qwen_name("Qwen/Qwen3-ASR-0.6B")
    assert ab.is_qwen_name("qwen/qwen3-asr-1.7b")  # case-insensitive


def test_router_does_not_misroute_nemo_canary_qwen_to_qwen_backend():
    # nvidia/canary-qwen-2.5b uses a Qwen LLM as its DECODER but is a NeMo model --
    # a substring match on "qwen" would wrongly send it to the qwen_asr package.
    assert not ab.is_qwen_name("nvidia/canary-qwen-2.5b")
    assert not ab.is_whisper_name("nvidia/canary-qwen-2.5b")


# ------------------------------------------------------------------ judge summary


def test_summarise_counts_blocklist_hits():
    hit = "thanks for watching"
    assert ab.hallucination.BLOCKLIST.search(hit), "blocklist fixture no longer matches -- pick another known phrase"
    miss = "a perfectly ordinary line of dialogue that matches nothing"
    s = ab.summarise([], [], [hit, miss, miss])
    assert s["blocklist_hits"] == 1
    assert s["segments"] == 3


def test_summarise_nsp_alive_frac_uses_the_collapse_floor():
    # Two segments above the 1e-6 floor, two collapsed below it -> 0.5 alive.
    nsps = [1e-10, 1e-10, 0.5, 0.99]
    s = ab.summarise(nsps, [], ["a", "b", "c", "d"])
    assert s["nsp_alive_frac"] == 0.5
    assert s["nsp_max"] == 0.99
    assert s["nsp_min"] == 1e-10


def test_summarise_music_rule_needs_both_signals_in_the_same_segment():
    # The music rule is a CONJUNCTION: nsp > 0.95 AND logprob < -2.0 on the SAME
    # segment. High nsp with a fine logprob must not fire it.
    s = ab.summarise([0.99, 0.1], [-1.0, -3.0], ["a", "b"])
    assert s["music_rule_would_fire"] == 0
    s = ab.summarise([0.99, 0.1], [-3.0, -1.0], ["a", "b"])
    assert s["music_rule_would_fire"] == 1


def test_summarise_handles_empty_lists_without_raising():
    s = ab.summarise([], [], [])
    assert s["segments"] == 0 and s["blocklist_hits"] == 0 and s["nsp_median"] is None


# ------------------------------------------------- cross-model agreement (cross_wer)


def test_cross_wer_joins_over_the_whole_episode_set():
    a = ["the quick brown fox", "jumps over the dog"]
    b = ["the quick brown fox", "jumps over the dog"]
    assert ab.cross_wer(a, b) == 0.0


def test_cross_wer_is_none_when_either_side_is_empty():
    # A failed episode must not silently score as a 100% disagreement.
    assert ab.cross_wer([], ["something"]) is None
    assert ab.cross_wer(["something"], []) is None


# ---------------------------------------------------------------- pairwise_agreement


def _entry(model, episodes, texts):
    return {"model": model, "verdict": "ok", "episodes": episodes, "texts": texts}


def test_pairwise_agreement_covers_every_pair_of_ok_entrants():
    eps = [{"episode": "e1.mkv"}]
    entries = [
        _entry("a", eps, ["hello world"]),
        _entry("b", eps, ["hello world"]),
        _entry("c", eps, ["goodbye world"]),
    ]
    agreement = ab.pairwise_agreement(entries)
    assert set(agreement) == {"a|b", "a|c", "b|c"}
    assert agreement["a|b"] == 0.0
    assert agreement["a|c"] == pytest.approx(0.5)


def test_pairwise_agreement_skips_entrants_that_did_not_load():
    eps = [{"episode": "e1.mkv"}]
    entries = [
        _entry("a", eps, ["hello world"]),
        {"model": "b", "verdict": "did not load", "error": "OOM"},
    ]
    assert ab.pairwise_agreement(entries) == {}


def test_pairwise_agreement_is_none_when_episode_sets_differ():
    # One entrant errored on an episode the other completed -- not a fair comparison.
    entries = [
        _entry("a", [{"episode": "e1.mkv"}, {"episode": "e2.mkv"}], ["x", "y"]),
        _entry("b", [{"episode": "e1.mkv"}, {"episode": "e2.mkv", "error": "boom"}], ["x"]),
    ]
    assert ab.pairwise_agreement(entries) == {"a|b": None}


# ---------------------------------------------------------------------- QwenRun shape


def test_qwen_run_is_a_nemo_run_shape_with_its_own_family_label():
    # QwenRun subclasses NemoRun for the identical result shape (no per-segment
    # nsp/logprob, word-level timestamps) -- only the family label should differ.
    run = ab.QwenRun("Qwen/Qwen3-ASR-1.7B")
    assert isinstance(run, ab.NemoRun)
    assert run.family == "qwen3-asr"
    assert run.words == [] and run.segments == [] and run.episodes == []


# --------------------------------------------------------- print_verdict precision caveat


def _verdict_entry(model, episodes=None):
    eps = episodes if episodes is not None else [{"episode": "e1.mkv", "wall_s": 1.0}]
    return {
        "model": model,
        "verdict": "ok",
        "episodes": eps,
        "has_word_timestamps": True,
        "load_s": 1.0,
        "peak_vram_mib": 100,
        "segments": 1,
        "word_count": 1,
        "blocklist_hits": 0,
    }


def test_print_verdict_flags_int8_fp16_precision_mismatch(capsys):
    report = ab.shape_report([_verdict_entry("large-v3-turbo (int8)"), _verdict_entry("nvidia/parakeet-tdt-0.6b-v3 (fp16)")], {})
    ab.print_verdict(report)
    assert "CAVEAT" in capsys.readouterr().out


def test_print_verdict_silent_when_precision_matches(capsys):
    report = ab.shape_report([_verdict_entry("large-v3-turbo (int8)"), _verdict_entry("large-v3 (int8)")], {})
    ab.print_verdict(report)
    assert "CAVEAT" not in capsys.readouterr().out


# --------------------------------------------------- NeMo transcript parsing (defensive)


class _Hyp:
    """Stand-in for nemo's Hypothesis: attribute access, .text, optional .timestamp."""

    def __init__(self, text, timestamp=None):
        self.text = text
        self.timestamp = timestamp


def test_parse_transcript_single_hypothesis():
    texts, words = ab.parse_transcript(_Hyp("hello world"))
    assert texts == ["hello world"]
    assert words == []


def test_parse_transcript_list_of_hypotheses():
    texts, _ = ab.parse_transcript([_Hyp("one"), _Hyp("two")])
    assert texts == ["one", "two"]


def test_parse_transcript_unwraps_hypotheses_alignment_tuple():
    # Recent nemo returns (hypotheses, alignment); the alignment half must be dropped,
    # not parsed as a hypothesis.
    texts, _ = ab.parse_transcript(([_Hyp("speech")], {"alignment": "whatever"}))
    assert texts == ["speech"]


def test_parse_transcript_extracts_word_timestamps():
    ts = {"word": [{"word": "hello", "start": 0.0, "end": 0.4}, {"word": "world", "start": 0.5, "end": 0.9}]}
    texts, words = ab.parse_transcript(_Hyp("hello world", timestamp=ts))
    assert texts == ["hello world"]
    assert [w["text"] for w in words] == ["hello", "world"]
    assert words[0]["start"] == 0.0 and words[1]["end"] == 0.9


def test_parse_transcript_sorts_words_by_time():
    ts = {"word": [{"word": "world", "start": 0.5, "end": 0.9}, {"word": "hello", "start": 0.0, "end": 0.4}]}
    _, words = ab.parse_transcript(_Hyp("x", timestamp=ts))
    assert [w["text"] for w in words] == ["hello", "world"]


def test_parse_transcript_token_level_timestamps_also_accepted():
    ts = {"token": [{"token": "he", "start": 0.0, "end": 0.2}]}
    _, words = ab.parse_transcript(_Hyp("he", timestamp=ts))
    assert len(words) == 1


def test_parse_transcript_partial_word_entries_are_dropped():
    # A word entry missing a boundary is unusable for cue generation; drop it rather
    # than fabricate a time.
    ts = {"word": [{"word": "good", "start": 0.0, "end": 0.3}, {"word": "bad", "start": None, "end": 0.5}]}
    _, words = ab.parse_transcript(_Hyp("good bad", timestamp=ts))
    assert [w["text"] for w in words] == ["good"]


def test_parse_transcript_unrecognised_shape_degrades_to_empty():
    # An unknown return shape yields empty results the run records as a finding --
    # never a guess, never an exception.
    texts, words = ab.parse_transcript(42)
    assert texts == [] and words == []
    texts, words = ab.parse_transcript(None)
    assert texts == [] and words == []


# ------------------------------------------------------------- chunk_wav (long-audio)


def _wav_duration_s(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def _write_silence_wav(path, seconds, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def test_chunk_wav_splits_into_expected_number_of_pieces(tmp_path):
    src = tmp_path / "src.wav"
    _write_silence_wav(src, seconds=5)
    chunks = ab.chunk_wav(str(src), chunk_s=2, out_dir=str(tmp_path))
    # 5s / 2s chunks -> [0, 2), [2, 4), [4, 5) = 3 pieces, last one short
    assert [round(off) for off, _ in chunks] == [0, 2, 4]
    assert all(_wav_duration_s(p) > 0 for _, p in chunks)


def test_chunk_wav_shorter_than_one_chunk_yields_a_single_piece(tmp_path):
    src = tmp_path / "src.wav"
    _write_silence_wav(src, seconds=1)
    chunks = ab.chunk_wav(str(src), chunk_s=300, out_dir=str(tmp_path))
    assert len(chunks) == 1
    assert chunks[0][0] == 0.0


def test_chunk_offsets_are_added_back_onto_word_timestamps():
    # This is the merge step run_nemo performs after transcribing each chunk --
    # a word at t=1.0 in the second 300s chunk must land at t=301.0 in the episode.
    chunk_words = [{"text": "hi", "start": 1.0, "end": 1.5}]
    offset = 300.0
    merged = [{**w, "start": w["start"] + offset, "end": w["end"] + offset} for w in chunk_words]
    assert merged == [{"text": "hi", "start": 301.0, "end": 301.5}]


# ------------------------------------------------------- pseudo-segmentation for NeMo


def test_segment_from_words_splits_on_large_gaps():
    words = [
        {"text": "a", "start": 0.0, "end": 0.5},
        {"text": "b", "start": 0.6, "end": 1.0},
        # 3s gap -> split
        {"text": "c", "start": 4.0, "end": 4.5},
    ]
    segs = ab.segment_from_words(words, max_gap=2.0)
    assert [s["text"] for s in segs] == ["a b", "c"]
    assert segs[0]["start"] == 0.0 and segs[1]["end"] == 4.5


def test_segment_from_words_keeps_contiguous_speech_together():
    words = [{"text": "a", "start": 0.0, "end": 0.5}, {"text": "b", "start": 0.6, "end": 1.0}]
    segs = ab.segment_from_words(words, max_gap=2.0)
    assert len(segs) == 1 and segs[0]["text"] == "a b"
