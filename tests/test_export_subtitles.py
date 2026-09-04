"""Checks for tools/export_subtitles.py -- the relaxed sibling of export_reviewed.py.

export_reviewed.py gates on decision 11 (every queued line has a human verdict); measured
2026-08-31 against the real library, zero One Pace episodes qualify under that gate. This
tool gates on completion instead (a valid .dubtitles.done stamp matching the current video)
so a first "unreviewed, subject to improve" batch can ship while decision 11 stays intact
for a future reviewed release. See docs/superpowers/specs/2026-08-31-public-beta-design.md,
Workstream C.

TDD entry point. These tests are written against synthetic temp dirs before the tool
exists, so the first run must fail at import.
"""

import json
import os
import subprocess
import sys

import common

EP_SUFFIX = ".dubtitles.conf.json"


def _stem(tmp_path, show, season, episode, ext="mkv", video_bytes=b"x"):
    """One episode laid out two levels below its show so show_for() resolves to `show`
    the way the live pipeline does."""
    dir = tmp_path / show / season
    dir.mkdir(parents=True, exist_ok=True)
    stem = str(dir / episode)
    with open(stem + "." + ext, "wb") as f:
        f.write(video_bytes)
    return stem


def _conf(stem, cards):
    with open(stem + EP_SUFFIX, "w") as f:
        json.dump(cards, f)


def _stamp(stem, video):
    """A real .dubtitles.done stamp, written by the pipeline's own write_stamp -- so this
    fixture can never drift from what a real stamp looks like."""
    common.write_stamp(stem + common.STAMP_SUFFIX, video)


def test_completed_episodes_finds_an_episode_with_a_valid_matching_stamp(tmp_path):
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _stamp(ep, ep + ".mkv")

    assert es.completed_episodes("One Pace", str(tmp_path)) == [ep]


def test_completed_episodes_excludes_an_episode_with_no_stamp(tmp_path):
    import tools.export_subtitles as es

    _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")

    assert es.completed_episodes("One Pace", str(tmp_path)) == []


def test_completed_episodes_excludes_a_stamp_that_no_longer_matches_the_video(tmp_path):
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _stamp(ep, ep + ".mkv")
    # The video was replaced after the stamp was written (different size) -- stamp_valid's
    # own job, this test only proves completed_episodes actually delegates to it.
    with open(ep + ".mkv", "wb") as f:
        f.write(b"a completely different and longer file")

    assert es.completed_episodes("One Pace", str(tmp_path)) == []


def test_completed_episodes_excludes_a_different_show(tmp_path):
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "Trigun", "Season 01", "Trigun - S01E01")
    _stamp(ep, ep + ".mkv")

    assert es.completed_episodes("One Pace", str(tmp_path)) == []


def test_completed_episodes_walks_the_media_root_exactly_once(tmp_path, monkeypatch):
    """review_server measures this walk at 297s for 989 episodes over a network mount --
    a stat costs what a read costs there, so a second walk doubles a five-minute operation
    to produce nothing new. Breaks if any code path walks the media root more than once."""
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _stamp(ep, ep + ".mkv")

    walks = []
    real_walk = os.walk

    def counting_walk(top, *a, **kw):
        walks.append(top)
        return real_walk(top, *a, **kw)

    monkeypatch.setattr(es.os, "walk", counting_walk)
    es.completed_episodes("One Pace", str(tmp_path))

    assert len(walks) == 1, f"media root walked {len(walks)} times; it must be walked once"


def test_dialogue_srt_builds_a_correctly_numbered_timestamped_srt(tmp_path):
    import tools.export_subtitles as es

    ep = str(tmp_path / "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.5, "text": "hello"}, {"start": 62.25, "end": 64.0, "text": "world"}])

    expected = "1\n00:00:00,000 --> 00:00:02,500\nhello\n\n2\n00:01:02,250 --> 00:01:04,000\nworld\n"
    assert es.dialogue_srt(ep) == expected


def test_dialogue_srt_returns_none_when_conf_json_is_missing(tmp_path):
    import tools.export_subtitles as es

    ep = str(tmp_path / "One Pace - S31E01")
    assert es.dialogue_srt(ep) is None


def test_probe_duration_seconds_returns_the_parsed_float(tmp_path):
    import tools.export_subtitles as es

    class Result:
        returncode = 0
        stdout = json.dumps({"format": {"duration": "1425.5"}})

    assert es.probe_duration_seconds("video.mkv", run=lambda *a, **k: Result()) == 1425.5


def test_probe_duration_seconds_returns_none_on_nonzero_returncode(tmp_path):
    import tools.export_subtitles as es

    class Result:
        returncode = 1
        stdout = ""

    assert es.probe_duration_seconds("video.mkv", run=lambda *a, **k: Result()) is None


def test_dubtitles_stream_index_finds_the_matching_stream(tmp_path):
    import tools.export_subtitles as es

    payload = {
        "streams": [
            {"index": 2, "tags": {"title": "Signs"}},
            {"index": 3, "tags": {"title": "Dubtitles"}},
        ]
    }

    class Result:
        returncode = 0
        stdout = json.dumps(payload)

    assert es.dubtitles_stream_index("video.mkv", run=lambda *a, **k: Result()) == 3


def test_dubtitles_stream_index_returns_none_when_no_stream_matches(tmp_path):
    import tools.export_subtitles as es

    payload = {"streams": [{"index": 2, "tags": {"title": "Signs"}}]}

    class Result:
        returncode = 0
        stdout = json.dumps(payload)

    assert es.dubtitles_stream_index("video.mkv", run=lambda *a, **k: Result()) is None


# ------------------------------------------------------ published_title (release tags)


def test_published_title_strips_a_release_tag_block():
    import tools.export_subtitles as export_subtitles

    # The break this catches: the public repository publishing somebody's rip metadata as
    # the episode's name.
    assert (
        export_subtitles.published_title(
            "Solo Leveling (2024) - S02E04 - I Need to Stop Faking [HDTV-1080p][10bit][Opus 2.0][x265]"
        )
        == "Solo Leveling (2024) - S02E04 - I Need to Stop Faking"
    )


def test_published_title_strips_a_release_group_welded_to_the_tag_block():
    import tools.export_subtitles as export_subtitles

    assert (
        export_subtitles.published_title("One Pace - S31E24 - Usoland the Liar [WEBRip-1080p x265 10bit]-Trix")
        == "One Pace - S31E24 - Usoland the Liar"
    )


def test_published_title_leaves_an_already_clean_name_untouched():
    import tools.export_subtitles as export_subtitles

    # Idempotence is what keeps the 48 episodes already published from being renamed --
    # a changed title is a changed entry_key, which republishes the whole repository.
    clean = "One Pace - S31E01 - Arriving at Dressrosa! The Country of Passion, Love, and Toys!"
    assert export_subtitles.published_title(clean) == clean


def test_published_title_keeps_a_bracket_that_is_part_of_the_episode_title():
    import tools.export_subtitles as export_subtitles

    # Only a TRAILING tag block is release metadata. A bracket inside the title is the
    # show's own punctuation and must survive.
    assert (
        export_subtitles.published_title("Show - S01E01 - The [Redacted] Incident [WEBRip-1080p]")
        == "Show - S01E01 - The [Redacted] Incident"
    )


def test_published_title_strips_bare_unbracketed_release_tokens():
    import tools.export_subtitles as export_subtitles

    # Not every release brackets its tags. This library holds both shapes.
    assert export_subtitles.published_title("Cosmic Princess Kaguya! (2026) 1080p 6ch x265") == "Cosmic Princess Kaguya! (2026)"


def test_published_title_does_not_eat_ordinary_title_words():
    import tools.export_subtitles as export_subtitles

    # The break this catches: a vocabulary loose enough to swallow the end of a real title.
    for name in (
        "Show - S01E01 - The Great Escape",
        "Show - S01E02 - Magnum Opus",
        "Show - S01E03 - Proper Introductions",
    ):
        assert export_subtitles.published_title(name) == name


def test_published_title_of_a_name_that_is_only_a_tag_block_falls_back_to_the_original():
    import tools.export_subtitles as export_subtitles

    # Never publish an empty filename: if stripping would leave nothing, the raw basename
    # is the lesser evil and is visibly wrong rather than silently missing.
    assert export_subtitles.published_title("[WEBRip-1080p]") == "[WEBRip-1080p]"


def test_export_episode_writes_the_srt_and_returns_the_manifest_entry(tmp_path):
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])
    out_root = tmp_path / "out"

    entry = es.export_episode(
        ep,
        str(out_root),
        probe=lambda video: 700.0,
        stream_finder=lambda video: 3,
        extractor=lambda video, index, out_path: True,
    )

    assert {k: entry[k] for k in ("show", "season", "episode_title", "duration_seconds", "status")} == {
        "show": "One Pace",
        "season": "Season 31",
        "episode_title": "One Pace - S31E01",
        "duration_seconds": 700.0,
        "status": "unreviewed",
    }
    assert entry["sha256"], "the entry carries the content hash change detection keys on"
    srt_path = out_root / "One Pace" / "Season 31" / "One Pace - S31E01.srt"
    assert srt_path.exists()
    assert srt_path.read_text() == "1\n00:00:00,000 --> 00:00:02,000\nhi\n"


def test_export_episode_returns_none_when_no_dubtitles_stream_is_found(tmp_path):
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])
    out_root = tmp_path / "out"

    entry = es.export_episode(
        ep,
        str(out_root),
        probe=lambda video: 700.0,
        stream_finder=lambda video: None,
        extractor=lambda video, index, out_path: True,
    )

    assert entry is None
    assert not (out_root / "One Pace").exists()


def test_export_episode_returns_none_when_ass_extraction_fails(tmp_path):
    """A failed extractor call must not ship a manifest entry promising an .ass file that
    was never written -- the README's per-episode contract is dialogue .srt AND merged
    .ass, not one of the two on a coin flip."""
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])
    out_root = tmp_path / "out"

    entry = es.export_episode(
        ep,
        str(out_root),
        probe=lambda video: 700.0,
        stream_finder=lambda video: 3,
        extractor=lambda video, index, out_path: False,
    )

    assert entry is None
    assert not (out_root / "One Pace" / "Season 31" / "One Pace - S31E01.ass").exists()
    assert not (out_root / "One Pace" / "Season 31" / "One Pace - S31E01.srt").exists()


def test_the_cli_writes_no_manifest_for_a_show_with_nothing_to_publish(tmp_path):
    """The break this catches: a manifest file created for every show in the library
    whether or not it publishes anything. The file's existence is the claim "this show is
    published"; on 2026-09-04 that would have committed 95 empty manifests."""
    prog = os.path.join(os.path.dirname(__file__), "..", "tools", "export_subtitles.py")
    proc = subprocess.run(
        [
            sys.executable,
            prog,
            "--show",
            "One Pace",
            "--media-root",
            str(tmp_path),
            "--out",
            str(tmp_path / "export"),
            "--manifest",
            str(tmp_path / "manifest.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "manifest.json").exists()


def test_an_existing_manifest_is_still_rewritten_when_the_show_drops_to_zero(tmp_path):
    """The other half of the rule above: skipping the write must not leave a stale manifest
    claiming episodes that are no longer published."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"show": "One Pace", "episode_title": "gone"}]))
    prog = os.path.join(os.path.dirname(__file__), "..", "tools", "export_subtitles.py")

    proc = subprocess.run(
        [
            sys.executable,
            prog,
            "--show",
            "One Pace",
            "--media-root",
            str(tmp_path),
            "--out",
            str(tmp_path / "export"),
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(manifest.read_text()) == []


# --- incremental publish: what counts as "changed" ------------------------------------


def _ass_writer(text):
    def extractor(video, index, out_path):
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        return True

    return extractor


def _plan(tmp_path, ep, published, ass_text, **kw):
    import tools.export_subtitles as es

    return es.plan_export(
        [ep],
        str(tmp_path / "out"),
        published,
        probe=lambda video: 700.0,
        stream_finder=lambda video: 3,
        extractor=_ass_writer(ass_text),
        **kw,
    )


def test_an_unchanged_episode_is_skipped_without_touching_ffmpeg(tmp_path):
    """The cheap pre-filter. A periodic sweep runs constantly and almost nothing has been
    re-muxed since the last one, so an episode whose stamp fingerprint still matches must
    not pay for an ffprobe+ffmpeg extraction to prove it did not change."""
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])
    video = ep + ".mkv"
    with open(ep + ".dubtitles.done", "w") as f:
        json.dump({"size": os.path.getsize(video), "mtime": os.path.getmtime(video), "muxed": True}, f)
    prior = {
        "show": "One Pace",
        "season": "Season 31",
        "episode_title": "One Pace - S31E01",
        "duration_seconds": 700.0,
        "status": "unreviewed",
        "sha256": "whatever",
        "source": es.source_fingerprint(ep),
    }
    published = {es.entry_key("One Pace", "Season 31", "One Pace - S31E01"): prior}

    def explode(*a, **k):
        raise AssertionError("an unchanged episode must not be extracted")

    entries, stats = es.plan_export([ep], str(tmp_path / "out"), published, stream_finder=explode)

    assert stats["unchanged"] == 1
    assert entries == [prior], "the published entry is carried forward verbatim"


def test_a_remux_that_produces_identical_bytes_is_not_republished(tmp_path):
    """The case a TEXT_VERSION bump creates for every show it does not actually affect.
    8->9 re-derives and re-muxes the WHOLE library while changing the output of only the 24
    shows carrying Japanese song lyrics. An mtime rule would republish everything to ship
    that; the content hash republishes what moved."""
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])

    first, _ = _plan(tmp_path, ep, {}, "[Events]\nsame")
    key = first[0]["show"] + "/" + first[0]["season"] + "/" + first[0]["episode_title"]
    # the video was re-muxed (fingerprint moves) but the exported bytes are identical
    stale = dict(first[0], source="0:0")
    entries, stats = _plan(tmp_path, ep, {key: stale}, "[Events]\nsame")

    assert stats["rederived"] == 1 and stats["updated"] == 0
    assert entries[0]["sha256"] == first[0]["sha256"]


def test_changed_content_is_reported_as_needing_republish(tmp_path):
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E01")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])

    first, _ = _plan(tmp_path, ep, {}, "[Events]\nbefore")
    key = first[0]["show"] + "/" + first[0]["season"] + "/" + first[0]["episode_title"]
    stale = dict(first[0], source="0:0")
    entries, stats = _plan(tmp_path, ep, {key: stale}, "[Events]\nafter")

    assert stats["updated"] == 1 and stats["rederived"] == 0
    assert entries[0]["sha256"] != first[0]["sha256"]


def test_two_encodes_of_one_episode_publish_once_and_are_counted(tmp_path):
    """The break this catches: two library files whose release tags differ collapse to one
    published name, so the second silently overwrites the first and the manifest keeps two
    entries under one key -- which republishes forever as the two encodes alternate.

    Measured 2026-09-04 on the real library: 19 titles, 38 files, all JUJUTSU KAISEN /
    MARRIAGETOXIN duplicates that differ only by a `[JA+EN]` tag."""
    import tools.export_subtitles as es

    a = _stem(tmp_path, "Show", "Season 01", "Show - S01E01 - Title [WEBDL-1080p][x264]-Grp")
    b = _stem(tmp_path, "Show", "Season 01", "Show - S01E01 - Title [WEBDL-1080p][x264][JA+EN]-Grp")
    for ep in (a, b):
        _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])
    out_root = tmp_path / "out"

    entries, stats = es.plan_export(
        [b, a],  # reversed on purpose: the winner must not depend on walk order
        str(out_root),
        {},
        probe=lambda video: 700.0,
        stream_finder=lambda video: 3,
        extractor=lambda video, index, out_path: True,
    )

    assert [e["episode_title"] for e in entries] == ["Show - S01E01 - Title"]
    assert stats["duplicate"] == 1
    assert stats["new"] == 1


def test_an_unchanged_episode_is_matched_through_its_published_title(tmp_path):
    """The break this catches: plan_export keying on the RAW basename while the manifest
    holds the stripped one -- every episode would then look new on every single run."""
    import tools.export_subtitles as es

    ep = _stem(tmp_path, "Show", "Season 01", "Show - S01E01 - Title [WEBDL-1080p][x264]-Grp")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "hi"}])
    _stamp(ep, ep + ".mkv")
    published = {
        es.entry_key("Show", "Season 01", "Show - S01E01 - Title"): {
            "show": "Show",
            "season": "Season 01",
            "episode_title": "Show - S01E01 - Title",
            "source": es.source_fingerprint(ep),
            "sha256": "whatever",
        }
    }

    entries, stats = es.plan_export(
        [ep],
        str(tmp_path / "out"),
        published,
        stream_finder=lambda video: (_ for _ in ()).throw(AssertionError("must not extract")),
    )

    assert stats["unchanged"] == 1 and len(entries) == 1


def test_a_missing_or_corrupt_manifest_publishes_everything(tmp_path):
    """Both mean "no reliable record of what is out there". Over-publishing is the safe
    direction; the alternative is silently withholding an episode that changed."""
    import tools.export_subtitles as es

    assert es.read_manifest(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert es.read_manifest(str(bad)) == {}


def test_publish_refuses_an_environment_without_git(tmp_path):
    """The break this catches: publish_subtitles.sh treating a missing git as "nothing
    changed" and exiting 0. Observed 2026-09-04 -- the container image carried no git, so a
    full library sweep reported success and published nothing, twice a day, silently."""
    import shutil

    repo = tmp_path / "subs"
    (repo / ".git").mkdir(parents=True)
    (tmp_path / "media").mkdir()
    empty_path = tmp_path / "bin"
    empty_path.mkdir()
    for tool in ("sh", "find", "sort", "wc", "python3", "date"):
        found = shutil.which(tool)
        if found:
            os.symlink(found, empty_path / tool)

    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "publish_subtitles.sh")
    proc = subprocess.run(
        ["sh", script],
        env={
            "PATH": str(empty_path),
            "SUBS_REPO": str(repo),
            "MEDIA_ROOT": str(tmp_path / "media"),
            "APP_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "git is not installed" in proc.stderr
