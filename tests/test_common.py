"""Unit tests for common.py's dialogue-selection helpers (T1 hoist from repair.py):
is_dialogue_event(), dialogue_density_score(), dialogue_event_count(), and
dialogue_intervals(). The predicate/regexes are byte-identical to repair.py's
pre-refactor dialogue_intervals() -- these tests pin that selection logic with
synthetic pysubs2 fixtures (no media, no ffmpeg) plus a hermetic extraction-pipeline
test that monkeypatches eng_sub_streams/extract_sub the same way
tests/test_dub_signs_merge.py does for dsm.build().

Also covers the strip-at-mux/context-isolation additions (see
docs/superpowers/specs/2026-07-26-strip-and-isolate-old-dubtitles-design.md): the
TRACK_NAME marker + _track_title() helper, eng_sub_streams()'s exclusion of our own
"Dubtitles" track, and the pipeline-version field on the .dubtitles.done stamp."""
import json
import types

import pysubs2

import common


def ev(text="hello", style="Default", start=0, end=1000, comment=False):
    return pysubs2.SSAEvent(text=text, style=style, start=start, end=end,
                             type="Comment" if comment else "Dialogue")


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
    assert share == 3 / 5   # comment excluded from the denominator


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


def test_dialogue_event_count_counts_only_dialogue(monkeypatch):
    sub = pysubs2.SSAFile()
    sub.events = [
        ev(text="Real line one.", style="Default"),
        ev(text="Real line two.", style="Default"),
        ev(text=r"{\pos(1,1)}sign", style="Text"),
    ]
    monkeypatch.setattr(common, "extract_sub", _fake_extract_from(sub))
    assert common.dialogue_event_count("fake-video.mkv", 0) == 2


def test_dialogue_event_count_extraction_failure_returns_zero(monkeypatch):
    monkeypatch.setattr(common, "extract_sub", lambda video, idx, out: False)
    assert common.dialogue_event_count("fake-video.mkv", 0) == 0


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
    assert common.dialogue_intervals("fake-video.mkv", stream_indices=[0, 1]) == [
        (0.0, 1.0, "Only line.")
    ]


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


# --- strip-at-mux: TRACK_NAME marker + _track_title() -------------------------

def test_track_name_and_version_constants():
    """The canonical marker for our own generated track (mux.py sets it as the mkv
    track name; every context reader excludes it) plus the stamp version constants."""
    assert common.TRACK_NAME == "Dubtitles"
    assert common.PIPELINE_VERSION >= 1
    assert common.GRANDFATHER_VERSION == 1


def test_track_title_reads_and_strips_tag():
    assert common._track_title({"tags": {"title": "Dubtitles"}}) == "Dubtitles"
    assert common._track_title({"tags": {"title": "  Dubtitles  "}}) == "Dubtitles"


def test_track_title_missing_or_null_tags_is_empty_string():
    assert common._track_title({}) == ""
    assert common._track_title({"tags": None}) == ""
    assert common._track_title({"tags": {"title": None}}) == ""


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
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([
        _sub(2, title="English (Fansub)"),
        _sub(3, title=common.TRACK_NAME),
    ]))
    assert common.eng_sub_streams("fake.mkv", {"eng"}) == [2]


def test_eng_sub_streams_excludes_dubtitles_track_with_padded_title(monkeypatch):
    monkeypatch.setattr(common, "subprocess", _fake_ffprobe([
        _sub(3, title="  Dubtitles  "),
    ]))
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
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    assert common.read_stamp(sp)["version"] == common.PIPELINE_VERSION


def test_stamp_valid_rejects_a_stamp_from_an_older_pipeline_version(tmp_path, monkeypatch):
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    stamp = common.read_stamp(sp)
    monkeypatch.setattr(common, "PIPELINE_VERSION", common.PIPELINE_VERSION + 1)
    assert not common.stamp_valid(stamp, str(v))     # stale output -> regenerate in place


def test_stamp_valid_accepts_a_stamp_at_the_current_version(tmp_path):
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + common.STAMP_SUFFIX))
    common.write_stamp(sp, str(v))
    assert common.stamp_valid(common.read_stamp(sp), str(v))


def test_stamp_valid_grandfathers_a_versionless_stamp(tmp_path):
    """A stamp written before this feature has no "version" key; it counts as
    GRANDFATHER_VERSION, so the rollout regenerates nothing while
    PIPELINE_VERSION == GRANDFATHER_VERSION."""
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    st = v.stat()
    old = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True}
    assert common.stamp_valid(old, str(v)) is (common.PIPELINE_VERSION == common.GRANDFATHER_VERSION)


def test_stamp_valid_rejects_a_versionless_stamp_after_a_version_bump(tmp_path, monkeypatch):
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    st = v.stat()
    old = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True}
    monkeypatch.setattr(common, "PIPELINE_VERSION", common.GRANDFATHER_VERSION + 1)
    assert not common.stamp_valid(old, str(v))
