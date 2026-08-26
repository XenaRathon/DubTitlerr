"""Unit tests for common.py's dialogue-selection helpers (T1 hoist from repair.py):
is_dialogue_event(), dialogue_density_score(), and
dialogue_intervals(). The predicate/regexes are byte-identical to repair.py's
pre-refactor dialogue_intervals() -- these tests pin that selection logic with
synthetic pysubs2 fixtures (no media, no ffmpeg) plus a hermetic extraction-pipeline
test that monkeypatches eng_sub_streams/extract_sub the same way
tests/test_dub_signs_merge.py does for dsm.build().

Also covers the strip-at-mux/context-isolation additions (see
docs/superpowers/specs/2026-07-26-strip-and-isolate-old-dubtitles-design.md): the
TRACK_NAME marker + stream_title()/is_our_track() helpers, eng_sub_streams()'s exclusion of our own
"Dubtitles" track, and the pipeline-version field on the .dubtitles.done stamp."""

import json
import os
import types

import pysubs2

import common


def ev(text="hello", style="Default", start=0, end=1000, comment=False):
    return pysubs2.SSAEvent(text=text, style=style, start=start, end=end, type="Comment" if comment else "Dialogue")


# --- is_dialogue_event() matrix ----------------------------------------------


def test_is_dialogue_event_accepts_plain_dialogue():
    assert common.is_dialogue_event(ev(text="Just talking.", style="Default"))


def test_is_dialogue_event_rejects_karaoke_tag():
    assert not common.is_dialogue_event(ev(text=r"{\k30}ka{\k30}ra{\k30}oke", style="Text"))


def test_is_dialogue_event_rejects_positioned_sign():
    assert not common.is_dialogue_event(ev(text=r"{\pos(100,200)}Sign text", style="Text"))


def test_is_dialogue_event_rejects_top_aligned_an_tag():
    assert not common.is_dialogue_event(ev(text=r"{\an8}Top text", style="Default"))


def test_is_dialogue_event_accepts_an2_bottom_center():
    # \an2 (bottom-center, the default alignment) is deliberately excluded from the
    # POSITIONED character class -- a normal dialogue line tagged \an2 is still dialogue.
    assert common.is_dialogue_event(ev(text=r"{\an2}Normal position text", style="Default"))


def test_is_dialogue_event_rejects_sign_style():
    assert not common.is_dialogue_event(ev(text="plain text, no override tags", style="Sign"))


def test_is_dialogue_event_rejects_song_style():
    assert not common.is_dialogue_event(ev(text="la la la", style="Song"))


def test_is_dialogue_event_rejects_warning_style():
    assert not common.is_dialogue_event(ev(text="junk row", style="Warning"))


def test_is_dialogue_event_rejects_comment():
    assert not common.is_dialogue_event(ev(text="Just talking.", style="Default", comment=True))


def test_is_dialogue_event_rejects_tag_only_empty_text():
    # override tags with no visible text left after stripping -> empty plaintext, not a
    # dialogue cue, even though neither KARAOKE/POSITIONED nor an excluded style fired.
    assert not common.is_dialogue_event(ev(text=r"{\i1}{\i0}", style="Default"))


# --- dialogue_density_score() -------------------------------------------------


def test_dialogue_density_score_empty_list():
    assert common.dialogue_density_score([]) == (0, 0.0)


def test_dialogue_density_score_all_comments():
    events = [ev(text="hidden", comment=True), ev(text="also hidden", comment=True)]
    assert common.dialogue_density_score(events) == (0, 0.0)


def test_dialogue_density_score_mixed_track():
    events = [
        ev(text="Line one.", style="Default"),
        ev(text="Line two.", style="Default"),
        ev(text="Line three.", style="Default"),
        ev(text="sign one", style="Sign"),
        ev(text="sign two", style="Sign"),
        ev(text="skipped", comment=True),
    ]
    count, share = common.dialogue_density_score(events)
    assert count == 3
    assert share == 3 / 5  # comment excluded from the denominator


def test_dialogue_density_score_signs_only_track_scores_low():
    events = [ev(text="sign", style="Sign"), ev(text=r"{\k30}song", style="Text")]
    count, share = common.dialogue_density_score(events)
    assert count == 0
    assert share == 0.0


# --- dialogue_event_count() / dialogue_intervals() extraction pipeline -------


def _fake_extract_from(subfile):
    def fake_extract(video, idx, out_path):
        subfile.save(out_path)
        return True

    return fake_extract


def test_dialogue_intervals_explicit_stream_indices_filters_and_sorts(monkeypatch):
    sub0 = pysubs2.SSAFile()
    sub0.events = [
        ev(text="Second dialogue line.", style="Default", start=5000, end=6000),
        ev(text=r"{\k20}karaoke stuff", style="Text", start=0, end=1000),
    ]
    sub1 = pysubs2.SSAFile()
    sub1.events = [ev(text="First dialogue line.", style="Default", start=1000, end=2000)]

    def fake_extract(video, idx, out_path):
        (sub0 if idx == 0 else sub1).save(out_path)
        return True

    monkeypatch.setattr(common, "extract_sub", fake_extract)
    ivals = common.dialogue_intervals("fake-video.mkv", stream_indices=[0, 1])

    assert ivals == [
        (1.0, 2.0, "First dialogue line."),
        (5.0, 6.0, "Second dialogue line."),
    ]


def test_dialogue_intervals_skips_stream_on_extraction_failure(monkeypatch):
    sub1 = pysubs2.SSAFile()
    sub1.events = [ev(text="Only line.", style="Default", start=0, end=1000)]

    def fake_extract_writing(video, idx, out_path):
        if idx == 0:
            return False
        sub1.save(out_path)
        return True

    monkeypatch.setattr(common, "extract_sub", fake_extract_writing)
    assert common.dialogue_intervals("fake-video.mkv", stream_indices=[0, 1]) == [(0.0, 1.0, "Only line.")]


def test_dialogue_intervals_skips_unparseable_stream(monkeypatch):
    def fake_extract(video, idx, out_path):
        with open(out_path, "wb") as f:
            f.write(b"\x00\x01not a subtitle file")
        return True

    monkeypatch.setattr(common, "extract_sub", fake_extract)
    assert common.dialogue_intervals("fake-video.mkv", stream_indices=[0]) == []


def test_dialogue_intervals_default_none_uses_eng_sub_streams(monkeypatch):
    """stream_indices=None must reproduce repair.py's pre-refactor all-stream behavior:
    resolve streams via eng_sub_streams(video, SUB_LANGS), scan each, merge + sort."""
    sub = pysubs2.SSAFile()
    sub.events = [ev(text="Only line.", style="Default", start=2000, end=3000)]

    seen_langs = []

    def fake_eng_sub_streams(video, langs):
        seen_langs.append(langs)
        return [3]

    def fake_extract(video, idx, out_path):
        assert idx == 3
        sub.save(out_path)
        return True

    monkeypatch.setattr(common, "eng_sub_streams", fake_eng_sub_streams)
    monkeypatch.setattr(common, "extract_sub", fake_extract)

    assert common.dialogue_intervals("fake-video.mkv") == [(2.0, 3.0, "Only line.")]
    assert seen_langs == [common.SUB_LANGS]


# --- strip-at-mux: TRACK_NAME marker + stream_title()/is_our_track() ---------


def test_track_name_and_version_constants():
    """The canonical marker for our own generated track (mux.py sets it as the mkv
    track name; every context reader excludes it) plus the stamp version constants."""
    assert common.TRACK_NAME == "Dubtitles"
    assert common.TRANSCRIBE_VERSION >= 1
    assert common.TEXT_VERSION >= 1
    assert common.GRANDFATHER_VERSION == 1


def test_stream_title_reads_and_strips_tag():
    assert common.stream_title({"tags": {"title": "Dubtitles"}}) == "Dubtitles"
    assert common.stream_title({"tags": {"title": "  Dubtitles  "}}) == "Dubtitles"


def test_stream_title_missing_or_null_tags_is_empty_string():
    assert common.stream_title({}) == ""
    assert common.stream_title({"tags": None}) == ""
    assert common.stream_title({"tags": {"title": None}}) == ""


def test_is_our_track_matches_the_marker_and_tolerates_padding_and_none():
    """One predicate for both shapes: ffprobe's tags.title and mkvmerge's
    properties.track_name. If these two ever disagreed, a track could be excluded from
    context but KEPT at mux -- a silent duplicate."""
    assert common.is_our_track("Dubtitles")
    assert common.is_our_track("  Dubtitles  ")
    assert not common.is_our_track(None)
    assert not common.is_our_track("")
    assert not common.is_our_track("English (Fansub)")


# --- eng_sub_streams(): never return our own Dubtitles track ------------------


def _fake_ffprobe(streams):
    """Stand in for common.subprocess so eng_sub_streams() sees a canned ffprobe -of json
    payload; records the argv so the test can assert the query itself asks for the title."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(stdout=json.dumps({"streams": streams}), returncode=0)

    return types.SimpleNamespace(run=run, DEVNULL=-3, calls=calls)


def _sub(index, lang="eng", codec="ass", title=None):
    tags = {"language": lang}
    if title is not None:
        tags["title"] = title
    return {"index": index, "codec_name": codec, "tags": tags}


def test_eng_sub_streams_ffprobe_query_requests_the_title_tag(monkeypatch):
    """The title filter is only meaningful if ffprobe is asked for stream_tags=title --
    without it every stream comes back title-less and the exclusion silently no-ops."""
    fake = _fake_ffprobe([])
    monkeypatch.setattr(common, "subprocess", fake)
    common.eng_sub_streams("fake.mkv", {"eng"})
    entries = fake.calls[0][fake.calls[0].index("-show_entries") + 1]
    assert "title" in entries.split(":")[-1]


def test_eng_sub_streams_excludes_our_own_dubtitles_track(monkeypatch):
    monkeypatch.setattr(
        common,
        "subprocess",
        _fake_ffprobe(
            [
                _sub(2, title="English (Fansub)"),
                _sub(3, title=common.TRACK_NAME),
            ]
        ),
    )
    assert common.eng_sub_streams("fake.mkv", {"eng"}) == [2]


def test_eng_sub_streams_excludes_dubtitles_track_with_padded_title(monkeypatch):
    monkeypatch.setattr(
        common,
        "subprocess",
        _fake_ffprobe(
            [
                _sub(3, title="  Dubtitles  "),
            ]
        ),
    )
    assert common.eng_sub_streams("fake.mkv", {"eng"}) == []


def test_eng_sub_streams_keeps_untitled_english_tracks(monkeypatch):
    """A genuine fansub track usually has no title tag at all -- the exclusion must not
    swallow it (a missing title is not our marker)."""
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([_sub(2), _sub(4, codec="ssa")]))
    assert common.eng_sub_streams("fake.mkv", {"eng"}) == [2, 4]


def test_eng_sub_streams_returns_empty_when_only_track_is_the_dubtitle(monkeypatch):
    """No fallback: an episode whose only English sub is our own old output yields no
    reference at all, so the pipeline runs reference-free rather than reading itself."""
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([_sub(2, title=common.TRACK_NAME)]))
    assert common.eng_sub_streams("fake.mkv", {"eng"}) == []


# --- pipeline-version stamp ---------------------------------------------------


def test_write_stamp_records_the_pipeline_version(tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    assert common.read_stamp(sp)["version"] == common.TEXT_VERSION


def test_stamp_valid_rejects_a_stamp_from_an_older_pipeline_version(tmp_path, monkeypatch):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    stamp = common.read_stamp(sp)
    monkeypatch.setattr(common, "TEXT_VERSION", common.TEXT_VERSION + 1)
    assert not common.stamp_valid(stamp, str(v))  # stale output -> regenerate in place


def test_stamp_valid_accepts_a_stamp_at_the_current_version(tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    assert common.stamp_valid(common.read_stamp(sp), str(v))


def test_stamp_valid_grandfathers_a_versionless_stamp(tmp_path):
    """A stamp written before this feature has no "version" key; it counts as
    GRANDFATHER_VERSION in BOTH tiers, so it is current only while both tiers still sit
    at GRANDFATHER_VERSION. They no longer do (4/5), so such a stamp is stale -- which
    is correct: it predates every output-changing fix v2 through v5."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    st = v.stat()
    old = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True}
    both_at_grandfather = (
        common.TRANSCRIBE_VERSION == common.GRANDFATHER_VERSION and common.TEXT_VERSION == common.GRANDFATHER_VERSION
    )
    assert common.stamp_valid(old, str(v)) is both_at_grandfather


def test_stamp_valid_rejects_a_versionless_stamp_after_a_version_bump(tmp_path, monkeypatch):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    st = v.stat()
    old = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True}
    monkeypatch.setattr(common, "TEXT_VERSION", common.GRANDFATHER_VERSION + 1)
    assert not common.stamp_valid(old, str(v))


def test_stamp_valid_tolerates_a_string_version(tmp_path):
    """A hand-edited/JSON-round-tripped stamp can carry "1" instead of 1. Comparing str
    to int raises TypeError, and this check runs OUTSIDE mux.process()'s try -- one bad
    sidecar would abort the whole sweep."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    st = v.stat()
    assert common.stamp_valid(
        {"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": str(common.TEXT_VERSION)}, str(v)
    )


def test_stamp_valid_rejects_an_uninterpretable_version(tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    st = v.stat()
    for bad in ("abc", None, [1]):
        assert not common.stamp_valid({"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": bad}, str(v))


# --- stale_version_stamp(): "this file, and its sidecars, are last version's output" ---


def _stamp_for(video, version):
    st = os.stat(video)
    return {"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": version}


def test_stale_version_stamp_true_for_our_own_older_output(tmp_path, monkeypatch):
    v = str(tmp_path / "ep.mkv")
    open(v, "wb").write(b"x" * 100)
    stamp = _stamp_for(v, common.TEXT_VERSION)
    monkeypatch.setattr(common, "TEXT_VERSION", common.TEXT_VERSION + 1)
    assert common.stale_version_stamp(stamp, v)


def test_stale_version_stamp_false_for_current_version(tmp_path):
    v = str(tmp_path / "ep.mkv")
    open(v, "wb").write(b"x" * 100)
    assert not common.stale_version_stamp(_stamp_for(v, common.TEXT_VERSION), v)


def test_stale_version_stamp_false_when_the_file_no_longer_matches(tmp_path, monkeypatch):
    """A replaced download is NOT "our old output" -- the stamp describes a different file,
    so nothing beside it can be attributed to a superseded pipeline run."""
    v = str(tmp_path / "ep.mkv")
    open(v, "wb").write(b"x" * 100)
    stamp = _stamp_for(v, common.TEXT_VERSION)
    open(v, "wb").write(b"y" * 250)
    monkeypatch.setattr(common, "TEXT_VERSION", common.TEXT_VERSION + 1)
    assert not common.stale_version_stamp(stamp, v)


def test_stale_version_stamp_false_for_no_stamp(tmp_path):
    v = str(tmp_path / "ep.mkv")
    open(v, "wb").write(b"x" * 100)
    assert not common.stale_version_stamp(None, v)


# --- signs_sub_streams(): prefer a dedicated signs/songs track ----------------
#
# 39 of the library's 79 releases ship more than one English ASS track, and the
# same signs are typeset in each of them. Merging all of them rendered every
# sign two or three times, offset by a few pixels. Nearly every such release
# names its signs track: "Signs & Songs", "S&S", "Signs/Songs", "English[Signs]",
# "Songs + Signs", or just "Forced" (a forced track is signs plus foreign-dialogue
# captions). When one exists, it is the release's own curated signs list and the
# only track we should lift from. Releases that name nothing usefully
# ("inid4c + SFX" / "Some-Stuff+SFX") keep the old per-event scan of every track.


def test_signs_streams_prefers_the_dedicated_signs_track(monkeypatch):
    monkeypatch.setattr(
        common,
        "subprocess",
        _fake_ffprobe(
            [
                _sub(2, title="Dialogue English English"),
                _sub(3, title="Signs & Songs English Forced English Forced"),
            ]
        ),
    )
    assert common.signs_sub_streams("fake.mkv", {"eng"}) == [3]


def test_signs_streams_recognises_the_abbreviated_and_slashed_spellings(monkeypatch):
    for title in (
        "S&S English English",
        "Signs/Songs [smol] English Forced",
        "English[Signs]",
        "Songs + Signs",
        "Signs and Songs(Hydes)",
    ):
        monkeypatch.setattr(common, "subprocess", _fake_ffprobe([_sub(2, title="Full Subtitles"), _sub(3, title=title)]))
        assert common.signs_sub_streams("fake.mkv", {"eng"}) == [3], title


def test_signs_streams_treats_a_forced_track_as_signs(monkeypatch):
    """Releases that ship ['Forced', ''] use the forced track for signs."""
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([_sub(2, title="Forced"), _sub(3, title="")]))
    assert common.signs_sub_streams("fake.mkv", {"eng"}) == [2]


def test_signs_streams_picks_only_one_when_a_release_ships_rival_signs_tracks(monkeypatch):
    """DAN DA DAN carries two groups' signs tracks. They are alternate typesettings
    of the SAME signs -- taking both is the double-render this fix exists to stop."""
    monkeypatch.setattr(
        common,
        "subprocess",
        _fake_ffprobe(
            [
                _sub(2, title="English [MALD] (CR Modified) English English"),
                _sub(5, title="English Signs/Songs [MALD] English Forced"),
                _sub(6, title="English Signs/Songs [CR] English Forced"),
            ]
        ),
    )
    assert common.signs_sub_streams("fake.mkv", {"eng"}) == [5]


def test_signs_streams_falls_back_to_every_track_when_none_is_named(monkeypatch):
    """No signs-ish title -> keep the historic behaviour: scan them all and classify
    per event, which is how releases with one mixed dialogue+signs track work."""
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([_sub(2, title="inid4c + SFX"), _sub(3, title="Some-Stuff+SFX")]))
    assert common.signs_sub_streams("fake.mkv", {"eng"}) == [2, 3]


def test_signs_streams_never_returns_our_own_dubtitles_track(monkeypatch):
    """Our own output is titled "Dubtitles" and would match nothing signs-ish, but it
    must not become the fallback either -- that re-lifts last version's signs."""
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([_sub(3, title=common.TRACK_NAME)]))
    assert common.signs_sub_streams("fake.mkv", {"eng"}) == []


def test_signs_streams_does_not_mistake_a_third_party_dubtitles_track_for_ours(monkeypatch):
    """Cowboy Bebop ships 'Dubtitles(Kaveman/Hydes)' -- a fansub, not our exact marker."""
    monkeypatch.setattr(
        common,
        "subprocess",
        _fake_ffprobe(
            [
                _sub(2, title="Dubtitles(Kaveman/Hydes)"),
                _sub(3, title="Signs and Songs(Hydes)"),
            ]
        ),
    )
    assert common.signs_sub_streams("fake.mkv", {"eng"}) == [3]


# --- shared LLM client: one backend switch for every stage --------------------
#
# repair.py owned the only ollama/llamacpp dispatch, so glossary_verify.py could not be
# pointed at anything but Ollama -- which meant the pipeline could not run entirely on
# one model. Both stages now go through common.llm_chat().
#
# The llama.cpp path posts to /v1/chat/completions (NOT /completion, which applies no
# chat template -- a templated instruct model returns nothing but newlines through it)
# and must pass chat_template_kwargs.enable_thinking=false: with the template applied but
# thinking on, this fork spends its whole budget on reasoning_content and returns an
# empty message.


def _capture_post(monkeypatch, reply):
    seen = {}

    def fake(url, body, timeout=120):
        seen["url"], seen["body"] = url, body
        return reply

    monkeypatch.setattr(common, "_post_json", fake)
    return seen


def test_llm_chat_llamacpp_applies_the_template_and_disables_thinking(monkeypatch):
    seen = _capture_post(monkeypatch, {"choices": [{"message": {"content": " Answer "}}]})
    out = common.llm_chat("PROMPT", backend="llamacpp", llamacpp_url="http://host:8090/v1/chat/completions")
    assert seen["url"] == "http://host:8090/v1/chat/completions"
    assert seen["body"]["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["body"]["temperature"] == 0
    assert "model" not in seen["body"]  # llama.cpp serves exactly one model
    assert out == "Answer"


def test_llm_chat_llamacpp_honours_max_tokens(monkeypatch):
    """Repair needs ~80 tokens for one line; adjudication returns a JSON object and needs
    far more. A shared 80-token cap would truncate every adjudication into invalid JSON."""
    seen = _capture_post(monkeypatch, {"choices": [{"message": {"content": "x"}}]})
    common.llm_chat("P", backend="llamacpp", llamacpp_url="http://h/v1/chat/completions", max_tokens=512)
    assert seen["body"]["max_tokens"] == 512


def test_llm_chat_ollama_keeps_its_original_request_shape(monkeypatch):
    seen = _capture_post(monkeypatch, {"response": " Answer "})
    out = common.llm_chat("PROMPT", backend="ollama", ollama_url="http://o/api/generate", model="qwen3:8b")
    assert seen["body"] == {
        "model": "qwen3:8b",
        "prompt": "PROMPT",
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    assert out == "Answer"


def test_llm_chat_returns_empty_string_on_transport_failure(monkeypatch):
    """Callers treat "" as "no answer". Raising here would abort a whole show mid-sweep."""

    def boom(url, body, timeout=120):
        raise OSError("connection refused")

    monkeypatch.setattr(common, "_post_json", boom)
    assert common.llm_chat("P", backend="ollama", ollama_url="http://o", model="m") == ""


def test_llm_chat_returns_empty_when_the_model_only_thought(monkeypatch):
    """Empty content with reasoning_content populated means thinking was not disabled.
    It must read as "no answer", never as text to use."""
    _capture_post(monkeypatch, {"choices": [{"message": {"content": "", "reasoning_content": "hmm"}}]})
    assert common.llm_chat("P", backend="llamacpp", llamacpp_url="http://h") == ""


def test_llm_chat_can_return_the_full_multi_line_reply(monkeypatch):
    """Repair wants only the first line (a subtitle is one line); adjudication returns a
    multi-line JSON object and must not be truncated to its opening brace."""
    _capture_post(monkeypatch, {"choices": [{"message": {"content": '{\n "a": 1\n}'}}]})
    out = common.llm_chat("P", backend="llamacpp", llamacpp_url="http://h", first_line=False)
    assert out == '{\n "a": 1\n}'


# --- stage-execution record in the stamp (2026-08-22) ---------------------------------


def test_old_stamp_without_stages_is_still_valid(tmp_path):
    """THE constraint on this change. A stamp written before `stages` existed must stay
    valid: if stamp_valid rejected it, every episode in the library would read as unprocessed
    and be fully re-transcribed -- ~12 GPU-hours to add a bookkeeping field."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 10)
    st = os.stat(v)
    old = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": common.TEXT_VERSION}
    assert common.stamp_valid(old, str(v)) is True


def test_stamp_records_which_stages_ran(tmp_path):
    """`.dubtitles.done` said an episode was done, not what "done" meant. An episode where
    repair never ran was indistinguishable from one where it ran and found nothing --
    merge_pass.sh has no `set -e` and checks no exit status, so a stage that died still
    reached MUX and still stamped."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 10)
    p = str(tmp_path / "ep.dubtitles.done")
    common.write_stamp(p, str(v), stages={"repair": False, "signs_merge": True, "punctuation": True})
    d = json.load(open(p))
    assert d["stages"]["repair"] is False
    assert d["stages"]["signs_merge"] is True
    assert d["version"] == common.TEXT_VERSION  # everything else unchanged


def test_stages_is_optional_and_omitted_when_absent(tmp_path):
    """Callers that do not know what ran must not claim they do."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 10)
    p = str(tmp_path / "ep.dubtitles.done")
    common.write_stamp(p, str(v))
    d = json.load(open(p))
    assert "stages" not in d
    assert common.stamp_valid(d, str(v)) is True


# --- two-tier idempotency (spec v5-two-tier-idempotency, S-1) ------------------


def _tier_stamp(tmp_path, **extra):
    """A stamp that matches its video exactly, so the tier read is what's under test."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    st = v.stat()
    stamp = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True}
    stamp.update(extra)
    return stamp, str(v)


def test_a_legacy_stamp_reads_both_tiers_from_its_single_version(tmp_path):
    """All 813 live stamps predate tiers. A stamp carrying only `version` must read as
    both tiers equal to it and must not raise -- if a legacy stamp stopped parsing, the
    whole library would read as unprocessed and be fully re-transcribed."""
    stamp, video = _tier_stamp(tmp_path, version=4)
    assert common.stale_tiers(stamp, video) == {"text"}


def test_adoption_constants_do_not_retranscribe_the_library():
    """TRANSCRIBE_VERSION adopts at 4, not 6: the 576 live v4 stamps are transcribe-fresh
    and only text-stale, so they migrate at watch-gated pace. Setting both to 6 would
    re-transcribe them all -- roughly two GPU-days for a bookkeeping change. Asserted on
    the real constants so that mistake cannot land quietly. TEXT_VERSION rises with every
    text-tier change (6 = the phonetic name guard); TRANSCRIBE_VERSION must NOT follow it."""
    assert common.TRANSCRIBE_VERSION == 4
    assert common.TEXT_VERSION == 6


def test_a_v2_stamp_is_stale_in_both_tiers(tmp_path):
    """The 236 episodes still at v2 were decoded by an older pipeline: both tiers behind."""
    stamp, video = _tier_stamp(tmp_path, version=2)
    assert common.stale_tiers(stamp, video) == {"transcribe", "text"}


def test_bumping_text_alone_never_marks_the_transcribe_tier(tmp_path, monkeypatch):
    """The whole point of the split: a text-only change must not reach the GPU."""
    stamp, video = _tier_stamp(tmp_path, transcribe_version=common.TRANSCRIBE_VERSION, text_version=common.TEXT_VERSION)
    monkeypatch.setattr(common, "TEXT_VERSION", common.TEXT_VERSION + 1)
    assert common.stale_tiers(stamp, video) == {"text"}


def test_bumping_transcribe_marks_both_tiers(tmp_path, monkeypatch):
    """New words invalidate everything derived from them."""
    stamp, video = _tier_stamp(tmp_path, transcribe_version=common.TRANSCRIBE_VERSION, text_version=common.TEXT_VERSION)
    monkeypatch.setattr(common, "TRANSCRIBE_VERSION", common.TRANSCRIBE_VERSION + 1)
    assert common.stale_tiers(stamp, video) == {"transcribe", "text"}


def test_a_stamp_describing_another_file_is_stale_in_both_tiers(tmp_path):
    """size/mtime mismatch outranks the tier read: this stamp is not about this video."""
    stamp, video = _tier_stamp(tmp_path, transcribe_version=common.TRANSCRIBE_VERSION, text_version=common.TEXT_VERSION)
    stamp["size"] = stamp["size"] + 1
    assert common.stale_tiers(stamp, video) == {"transcribe", "text"}


def test_a_corrupt_tier_value_is_stale_not_an_exception(tmp_path):
    """A hand-edited stamp must not abort a sweep over hundreds of episodes."""
    stamp, video = _tier_stamp(tmp_path, transcribe_version="four", text_version=None)
    assert common.stale_tiers(stamp, video) == {"transcribe", "text"}


def test_stamp_valid_is_exactly_nothing_stale(tmp_path):
    """stamp_valid keeps its meaning -- everything current -- so no caller changes."""
    stamp, video = _tier_stamp(tmp_path, transcribe_version=common.TRANSCRIBE_VERSION, text_version=common.TEXT_VERSION)
    assert common.stamp_valid(stamp, video)
    assert not common.stale_tiers(stamp, video)


def test_write_stamp_still_records_a_legacy_version_key(tmp_path):
    """An older build of the pipeline, and scripts/migrate_write_v1_stamps.py, read
    `version`. Dropping it would make every new stamp read as pre-versioning
    (GRANDFATHER_VERSION=1) to them, i.e. stale, i.e. a full re-transcribe."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    doc = common.read_stamp(sp)
    assert doc["transcribe_version"] == common.TRANSCRIBE_VERSION
    assert doc["text_version"] == common.TEXT_VERSION
    assert doc["version"] == common.TEXT_VERSION
