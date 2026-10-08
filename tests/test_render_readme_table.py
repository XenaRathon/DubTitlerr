"""tools/render_readme_table.py: the README's "What's here" table, generated at publish time.

Written test-first; on the first run the module does not exist, so every test fails at import.
"""

import json
import os
import shutil
import subprocess
import sys

START = "<!-- shows-table:start -->"
END = "<!-- shows-table:end -->"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _manifest(d, name, n, status="unreviewed"):
    entries = [{"show": name, "season": "S1", "episode_title": f"e{i}", "status": status} for i in range(n)]
    (d / f"{name}.json").write_text(json.dumps(entries), encoding="utf-8")


def _readme(p, body="old table\n"):
    p.write_text(f"# Title\n\nintro\n\n{START}\n{body}{END}\n\ntail\n", encoding="utf-8")


def _setup(tmp_path):
    m = tmp_path / "manifest"
    m.mkdir()
    return m, tmp_path / "README.md"


def test_table_content_and_ordering(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "Beta", 2)
    _manifest(m, "Alpha", 2)
    _manifest(m, "Big", 5)
    _readme(readme)

    r.render(str(m), str(readme), "2026-10-08")

    text = readme.read_text(encoding="utf-8")
    assert "As of 2026-10-08: **9 episodes across 3 shows**, all unreviewed. " in text
    assert "`manifest/` is the authoritative list." in text
    table = "| Show | Episodes |\n| --- | ---: |\n| Big | 5 |\n| Alpha | 2 |\n| Beta | 2 |\n"
    assert table in text
    # only the marked region changed
    assert text.startswith(f"# Title\n\nintro\n\n{START}\n")
    assert text.endswith(f"{END}\n\ntail\n")
    assert "old table" not in text


def test_tvdb_id_is_stripped_from_the_show_name(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "Sword Art Online {tvdb-259640}", 3)
    _readme(readme)

    r.render(str(m), str(readme), "2026-10-08")

    text = readme.read_text(encoding="utf-8")
    assert "| Sword Art Online | 3 |" in text
    assert "tvdb" not in text


def test_mixed_status_states_how_many_are_reviewed(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "A", 3)
    _manifest(m, "B", 2, status="reviewed")
    _readme(readme)

    r.render(str(m), str(readme), "2026-10-08")

    text = readme.read_text(encoding="utf-8")
    assert "**5 episodes across 2 shows**, 2 of 5 reviewed. " in text
    assert "all unreviewed" not in text


def test_same_manifests_on_a_later_date_leave_the_file_untouched(tmp_path):
    """A daily-changing date line must not turn into a daily noise commit."""
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "A", 3)
    _readme(readme)
    assert r.render(str(m), str(readme), "2026-10-08") is True
    first = readme.read_bytes()

    assert r.render(str(m), str(readme), "2026-10-09") is False

    assert readme.read_bytes() == first
    assert "As of 2026-10-08:" in readme.read_text(encoding="utf-8")  # the OLD date is kept


def test_a_changed_count_on_a_later_date_rewrites_with_the_new_date(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "A", 3)
    _readme(readme)
    r.render(str(m), str(readme), "2026-10-08")
    _manifest(m, "A", 4)

    assert r.render(str(m), str(readme), "2026-10-09") is True

    text = readme.read_text(encoding="utf-8")
    assert "As of 2026-10-09: **4 episodes across 1 shows**" in text
    assert "2026-10-08" not in text


def test_no_loadable_manifest_warns_and_leaves_the_readme_alone(tmp_path, capsys):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    (m / "Broken.json").write_text("{not json", encoding="utf-8")
    (m / "Dict.json").write_text("{}", encoding="utf-8")
    _readme(readme, body="keep me\n")
    before = readme.read_bytes()

    assert r.render(str(m), str(readme), "2026-10-08") is False
    assert readme.read_bytes() == before

    (m / "Broken.json").unlink()
    (m / "Dict.json").unlink()  # and an empty directory
    assert r.render(str(m), str(readme), "2026-10-08") is False
    assert readme.read_bytes() == before
    assert "no manifest" in capsys.readouterr().err


def test_missing_null_or_odd_status_and_non_dict_entries_count_as_unreviewed(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    (m / "A.json").write_text(
        json.dumps([{"show": "A"}, {"status": None}, {"status": 3}, "junk", 7, {"status": ""}, {"status": "reviewed"}]),
        encoding="utf-8",
    )
    _readme(readme)

    r.render(str(m), str(readme), "2026-10-08")

    text = readme.read_text(encoding="utf-8")
    assert "**7 episodes across 1 shows**, 1 of 7 reviewed. " in text


def test_nothing_is_reviewed_without_positive_evidence(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    (m / "A.json").write_text(json.dumps([{"show": "A"}, {"status": None}, "x"]), encoding="utf-8")
    _readme(readme)

    r.render(str(m), str(readme), "2026-10-08")

    assert "**3 episodes across 1 shows**, all unreviewed. " in readme.read_text(encoding="utf-8")


def test_missing_markers_change_nothing_and_warn(tmp_path, capsys):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "A", 3)
    original = "# Title\n\nhand written table\n"
    readme.write_text(original, encoding="utf-8")

    assert r.render(str(m), str(readme), "2026-10-08") is False

    assert readme.read_text(encoding="utf-8") == original
    assert "marker" in capsys.readouterr().err


def test_malformed_markers_change_nothing(tmp_path, capsys):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "A", 3)
    for bad in (
        f"x\n{END}\nmid\n{START}\ny\n",  # end before start
        f"x\n{START}\nmid\n",  # no end
        f"{START}\na\n{END}\n{START}\nb\n{END}\n",  # duplicated
    ):
        readme.write_text(bad, encoding="utf-8")
        assert r.render(str(m), str(readme), "2026-10-08") is False
        assert readme.read_text(encoding="utf-8") == bad
    assert "marker" in capsys.readouterr().err


def test_idempotent_for_same_inputs_and_date(tmp_path):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "A", 3)
    _readme(readme)

    assert r.render(str(m), str(readme), "2026-10-08") is True
    first = readme.read_bytes()
    assert r.render(str(m), str(readme), "2026-10-08") is False
    assert readme.read_bytes() == first


def test_bad_manifests_are_skipped_with_a_warning(tmp_path, capsys):
    import tools.render_readme_table as r

    m, readme = _setup(tmp_path)
    _manifest(m, "Good", 2)
    (m / "Broken.json").write_text("{not json", encoding="utf-8")
    (m / "Dict.json").write_text('{"a": 1}', encoding="utf-8")
    (m / "notes.txt").write_text("ignored", encoding="utf-8")
    _readme(readme)

    r.render(str(m), str(readme), "2026-10-08")

    text = readme.read_text(encoding="utf-8")
    assert "**2 episodes across 1 shows**" in text
    assert "| Good | 2 |" in text
    assert "Broken" not in text and "Dict" not in text
    err = capsys.readouterr().err
    assert "Broken.json" in err and "Dict.json" in err


def test_cli_renders_with_explicit_date(tmp_path):
    m, readme = _setup(tmp_path)
    _manifest(m, "A", 1)
    _readme(readme)

    proc = subprocess.run(
        [
            "python3",
            os.path.join(ROOT, "tools", "render_readme_table.py"),
            "--manifest-dir",
            str(m),
            "--readme",
            str(readme),
            "--today",
            "2026-01-02",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "As of 2026-01-02: **1 episodes across 1 shows**" in readme.read_text(encoding="utf-8")


# --- publish_subtitles.sh wiring ---------------------------------------------------------


def _seeded_checkout(tmp_path):
    bare = tmp_path / "remote.git"
    subs = tmp_path / "subs"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(subs)], check=True)
    (subs / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(subs), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(subs), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(subs), "push", "-q", "-u", "origin", "HEAD"], check=True)
    return bare, subs


def _run_publish(subs, tmp_path, **extra_env):
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    env = {
        "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
        "SUBS_REPO": str(subs),
        "MEDIA_ROOT": str(media),
        "APP_DIR": str(tmp_path),
        "HOME": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),  # HOME is a tmp dir: keep user site-packages
        **extra_env,
    }
    return subprocess.run(["sh", os.path.join(ROOT, "tools", "publish_subtitles.sh")], env=env, capture_output=True, text=True)


def test_publish_calls_the_renderer_before_the_porcelain_check_and_non_fatally():
    script = open(os.path.join(ROOT, "tools", "publish_subtitles.sh"), encoding="utf-8").read()
    call = script.index("$APP/tools/render_readme_table.py")
    assert call < script.index("git status --porcelain")
    assert call > script.index("\ndone\n")  # after the per-show loop
    line = script[call : script.index("\n", call)]
    assert '"$SUBS_REPO/manifest"' in script[call - 200 : call + 200]
    assert "README table not updated" in script[call : call + 400]
    assert line  # non-empty


def test_publish_updates_the_readme_table_and_commits_it(tmp_path):
    bare, subs = _seeded_checkout(tmp_path)
    (subs / "manifest").mkdir()
    _manifest(subs / "manifest", "Show {tvdb-1}", 2)
    (subs / "README.md").write_text(f"hi\n{START}\nstale\n{END}\n", encoding="utf-8")
    # APP_DIR=tmp_path in _run_publish, so give it the real tool
    (tmp_path / "tools").mkdir()
    shutil.copy(os.path.join(ROOT, "tools", "render_readme_table.py"), tmp_path / "tools")
    shutil.copy(os.path.join(ROOT, "common.py"), tmp_path)

    proc = _run_publish(subs, tmp_path, PUBLISH_APPLY="1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    readme = (subs / "README.md").read_text(encoding="utf-8")
    assert "| Show | 2 |" in readme and "stale" not in readme
    landed = subprocess.run(
        ["git", "-C", str(bare), "log", "-1", "--name-only", "--format="], capture_output=True, text=True
    ).stdout
    assert "README.md" in landed


def test_publish_survives_a_failing_renderer(tmp_path):
    _, subs = _seeded_checkout(tmp_path)
    (subs / "new.srt").write_text("1\n")
    # no tools/render_readme_table.py under APP_DIR -> python exits 2
    proc = _run_publish(subs, tmp_path, PUBLISH_APPLY="1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "README table not updated" in proc.stderr
    assert "pushed" in proc.stdout
