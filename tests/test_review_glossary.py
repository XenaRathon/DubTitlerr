"""The glossary editor backend (specs/webui-glossary-editor/spec.md): handlers only, no socket.

GLOSSARY_DIR is always a tmp_path -- these tests write glossary files and must never see /config."""

import hashlib
import json
import os

import pytest

import decisions
import glossary_lock
import review_glossary
import review_server

SHOW = "One Pace"

RAW = {
    "show": SHOW,
    "initial_prompt": "This is One Pace. Spell names correctly: Luffy.",
    "names": ["Luffy", "Zoro"],
    "phrases": ["Straw Hat Pirates"],
    "hard_fixes": {"lufi": "Luffy", "straw hat": "Straw Hat"},
    "verified": {"Luffy": {"source": "wiki", "at": "2026-09-01"}},
    "flagged": [{"term": "Zoro", "why": "alt spelling"}],
    "acquired": {"Nami": "wiki"},
    "known": ["Sanji"],
    "_curated": True,
    "unanchored_repair": True,
}
MACHINE = ("show", "initial_prompt", "verified", "flagged", "acquired", "known", "_curated", "unanchored_repair")


@pytest.fixture
def gdir(tmp_path, monkeypatch):
    d = tmp_path / "glossaries"
    d.mkdir()
    monkeypatch.setattr(decisions, "GLOSSARY_DIR", str(d))
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0")
    return d


def _put(gdir, name=SHOW, data=None, indent=2, newline=True):
    p = gdir / f"{name}.json"
    p.write_text(json.dumps(RAW if data is None else data, indent=indent, ensure_ascii=False) + ("\n" if newline else ""))
    return p


def _version(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post(gdir, p, **kw):
    body = {"show": SHOW, "op": "add", "key": "names", "term": "Nami", "value": None, "expected_version": _version(p)}
    body.update(kw)
    return review_glossary.handle("POST", "/api/glossary", body)


def _disk(p):
    return json.loads(p.read_text())


# --- list / detail -----------------------------------------------------------------------


def test_list_returns_sorted_stems_without_sidecars(gdir):
    for name in ("One Pace", "Cowboy Bebop (1998) {tvdb-76885}", "Trigun"):
        _put(gdir, name)
    for junk in (
        "One Pace.json.lock",
        "One Pace.review-pending.json",
        "One Pace.acquire-cache.json",
        "One Pace.journal.jsonl",
        "One Pace.lastrun.json",
        "One Pace.json.bak-20261012T100000Z",
        "notes.txt",
    ):
        (gdir / junk).write_text("{}")

    status, payload = review_glossary.handle("GET", "/api/glossary", {})

    assert status == 200
    assert payload == {"shows": ["Cowboy Bebop (1998) {tvdb-76885}", "One Pace", "Trigun"]}


def test_detail_round_trip_has_editable_keys_and_sha256_version(gdir):
    p = _put(gdir)

    status, payload = review_glossary.handle("GET", "/api/glossary", {"show": SHOW})

    assert status == 200
    assert payload == {
        "show": SHOW,
        "version": hashlib.sha256(p.read_bytes()).hexdigest(),
        "names": ["Luffy", "Zoro"],
        "phrases": ["Straw Hat Pirates"],
        "hard_fixes": {"lufi": "Luffy", "straw hat": "Straw Hat"},
    }


def test_detail_defaults_missing_editable_keys(gdir):
    _put(gdir, data={"show": SHOW})

    status, payload = review_glossary.handle("GET", "/api/glossary", {"show": SHOW})

    assert status == 200
    assert (payload["names"], payload["phrases"], payload["hard_fixes"]) == ([], [], {})


def test_unknown_show_is_404_on_get_and_post(gdir):
    _put(gdir)
    assert review_glossary.handle("GET", "/api/glossary", {"show": "Nope"}) == (404, {"error": "no such glossary"})
    status, payload = review_glossary.handle(
        "POST",
        "/api/glossary",
        {"show": "Nope", "op": "add", "key": "names", "term": "X", "expected_version": "v"},
    )
    assert (status, payload) == (404, {"error": "no such glossary"})
    assert not (gdir / "Nope.json").exists(), "the editor never creates a glossary"


@pytest.mark.parametrize("show", ["../etc/passwd", "a/b", "..", "One Pace\x00", "/abs", "a\\b"])
def test_traversal_in_show_is_400_and_reads_nothing(gdir, tmp_path, show):
    _put(gdir)
    (tmp_path / "etc").mkdir()
    assert review_glossary.handle("GET", "/api/glossary", {"show": show})[0] == 400
    status, _ = review_glossary.handle(
        "POST", "/api/glossary", {"show": show, "op": "add", "key": "names", "term": "X", "expected_version": "v"}
    )
    assert status == 400


def test_non_string_show_is_400(gdir):
    assert review_glossary.handle("GET", "/api/glossary", {"show": ["x"]})[0] == 400


def test_corrupt_and_unreadable_glossaries_are_500_and_untouched(gdir):
    p = gdir / f"{SHOW}.json"
    p.write_text("{not json")
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW}) == (500, {"error": "glossary corrupt"})
    status, payload = review_glossary.handle(
        "POST", "/api/glossary", {"show": SHOW, "op": "add", "key": "names", "term": "X", "expected_version": "v"}
    )
    assert (status, payload) == (500, {"error": "glossary corrupt"})
    assert p.read_text() == "{not json"
    assert [f.name for f in gdir.iterdir() if ".bak-" in f.name] == []

    p.write_text("[1, 2]")  # valid JSON, wrong shape
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW}) == (500, {"error": "glossary corrupt"})

    p.write_bytes(b"\xff\xfe\x00")  # not UTF-8
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW}) == (500, {"error": "glossary corrupt"})


def test_unreadable_file_is_500(gdir, monkeypatch):
    _put(gdir)
    real = os.open

    def boom(path, *a, **k):
        if str(path).endswith(f"{SHOW}.json"):
            raise PermissionError("denied")
        return real(path, *a, **k)

    monkeypatch.setattr(os, "open", boom)
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW}) == (500, {"error": "glossary unreadable"})


def test_wrong_method_or_path_is_404(gdir):
    assert review_glossary.handle("DELETE", "/api/glossary", {})[0] == 404


# --- writes ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, term, value, check",
    [
        ("names", "Nami", None, lambda d: d["names"] == ["Luffy", "Zoro", "Nami"]),
        ("phrases", "Going Merry", None, lambda d: d["phrases"] == ["Straw Hat Pirates", "Going Merry"]),
        ("hard_fixes", "zorro", "Zoro", lambda d: d["hard_fixes"]["zorro"] == "Zoro"),
    ],
)
def test_add_per_key(gdir, key, term, value, check):
    p = _put(gdir)
    status, payload = _post(gdir, p, op="add", key=key, term=term, value=value)
    assert status == 200, payload
    assert check(_disk(p))


@pytest.mark.parametrize(
    "key, term, value, check",
    [
        ("names", "Zoro", "Roronoa Zoro", lambda d: d["names"] == ["Luffy", "Roronoa Zoro"]),
        ("phrases", "Straw Hat Pirates", "Straw Hats Crew", lambda d: d["phrases"] == ["Straw Hats Crew"]),
        ("hard_fixes", "lufi", "Monkey D. Luffy", lambda d: d["hard_fixes"]["lufi"] == "Monkey D. Luffy"),
    ],
)
def test_update_per_key(gdir, key, term, value, check):
    p = _put(gdir)
    status, payload = _post(gdir, p, op="update", key=key, term=term, value=value)
    assert status == 200, payload
    assert check(_disk(p))


@pytest.mark.parametrize(
    "key, term, check",
    [
        ("names", "Zoro", lambda d: d["names"] == ["Luffy"]),
        ("phrases", "Straw Hat Pirates", lambda d: d["phrases"] == []),
        ("hard_fixes", "lufi", lambda d: "lufi" not in d["hard_fixes"]),
    ],
)
def test_delete_per_key(gdir, key, term, check):
    p = _put(gdir)
    status, payload = _post(gdir, p, op="delete", key=key, term=term, value="ignored")
    assert status == 200, payload
    assert check(_disk(p))


def test_update_renames_in_place_keeping_position(gdir):
    p = _put(gdir, data={**RAW, "names": ["A", "B", "C"]})
    _post(gdir, p, op="update", key="names", term="B", value="Bee")
    assert _disk(p)["names"] == ["A", "Bee", "C"]


def test_machine_keys_survive_every_op_unchanged(gdir):
    p = _put(gdir)
    for kw in (
        dict(op="add", key="names", term="Nami"),
        dict(op="update", key="phrases", term="Straw Hat Pirates", value="Straw Hat Crew"),
        dict(op="delete", key="hard_fixes", term="lufi"),
    ):
        status, payload = _post(gdir, p, **kw)
        assert status == 200, payload
    disk = _disk(p)
    assert {k: disk[k] for k in MACHINE} == {k: RAW[k] for k in MACHINE}
    assert list(disk) == list(RAW), "key order is kept"


def test_formatting_style_is_kept(gdir):
    p = _put(gdir, indent=4, newline=False)
    _post(gdir, p, op="add", key="names", term="Nami")
    text = p.read_text()
    assert text.startswith('{\n    "show"'), "4-space indent stays 4-space"
    assert not text.endswith("\n")

    p2 = _put(gdir, name="Other", data={**RAW, "show": "Other"}, indent=2, newline=True)
    _post(gdir, p2, show="Other", op="add", key="names", term="Nami")
    assert p2.read_text().startswith('{\n  "show"') and p2.read_text().endswith("\n")


def test_non_ascii_is_written_literally(gdir):
    p = _put(gdir, data={**RAW, "names": ["Café"]})
    _post(gdir, p, op="add", key="names", term="Nāmi")
    assert "Nāmi" in p.read_text() and "Café" in p.read_text()


def test_write_response_and_version_chain(gdir):
    p = _put(gdir)
    old = _version(p)
    status, payload = _post(gdir, p)
    assert status == 200
    assert payload["ok"] is True and payload["show"] == SHOW and payload["reapply_hint"] is True
    assert payload["version"] == _version(p) != old
    assert payload["backup"].startswith(f"{SHOW}.json.bak-")
    # the new version is usable as the next expected_version
    assert _post(gdir, p, term="Sanji", expected_version=payload["version"])[0] == 200


def test_backup_holds_the_prior_bytes(gdir):
    p = _put(gdir)
    before = p.read_bytes()
    _, payload = _post(gdir, p)
    assert (gdir / payload["backup"]).read_bytes() == before


def test_no_temp_files_left_and_listing_unchanged(gdir):
    p = _put(gdir)
    _post(gdir, p)
    left = sorted(f.name for f in gdir.iterdir() if ".bak-" not in f.name)
    assert left == [f"{SHOW}.json", f"{SHOW}.json.lock"] or left == [f"{SHOW}.json"]
    assert review_glossary.handle("GET", "/api/glossary", {})[1] == {"shows": [SHOW]}


def test_only_newest_20_backups_are_kept(gdir):
    p = _put(gdir)
    for i in range(25):
        (gdir / f"{SHOW}.json.bak-2026010{i // 10}T0000{i % 10:02d}Z").write_text(str(i))
    stale = sorted(f.name for f in gdir.iterdir() if ".bak-" in f.name)
    status, payload = _post(gdir, p)
    assert status == 200
    kept = sorted(f.name for f in gdir.iterdir() if ".bak-" in f.name)
    assert len(kept) == 20
    assert payload["backup"] in kept, "the backup just made is the newest and survives"
    assert set(kept) <= set(stale) | {payload["backup"]}
    assert stale[0] not in kept, "oldest are the ones pruned"


def test_prune_backups_ignores_other_glossaries_and_keeps_fewer_than_limit(gdir):
    p = _put(gdir)
    other = _put(gdir, name="Other")
    for i in range(3):
        (gdir / f"Other.json.bak-2026010{i}T000000Z").write_text("x")
        (gdir / f"{SHOW}.json.bak-2026010{i}T000000Z").write_text("x")
    review_glossary.prune_backups(str(p), keep=2)
    assert sorted(f.name for f in gdir.glob(f"{SHOW}.json.bak-*")) == [
        f"{SHOW}.json.bak-20260101T000000Z",
        f"{SHOW}.json.bak-20260102T000000Z",
    ], "the newest two survive, the oldest goes"
    assert len(list(gdir.glob("Other.json.bak-*"))) == 3
    assert other.exists()


def test_stale_version_is_409_and_writes_nothing(gdir):
    p = _put(gdir)
    before = p.read_bytes()
    status, payload = _post(gdir, p, expected_version="0" * 64)
    assert status == 409
    assert payload == {"error": "version conflict", "version": hashlib.sha256(before).hexdigest()}
    assert p.read_bytes() == before
    assert [f for f in gdir.iterdir() if ".bak-" in f.name] == []


def test_a_concurrent_edit_between_read_and_write_is_a_409(gdir):
    p = _put(gdir)
    v = _version(p)
    assert _post(gdir, p, term="First", expected_version=v)[0] == 200
    status, _ = _post(gdir, p, term="Second", expected_version=v)
    assert status == 409
    assert "Second" not in _disk(p)["names"]


def test_busy_lock_is_503_with_no_write_backup_or_prune(gdir):
    p = _put(gdir)
    before = p.read_bytes()
    for i in range(25):
        (gdir / f"{SHOW}.json.bak-2026010{i // 10}T0000{i % 10:02d}Z").write_text(str(i))
    backups = sorted(f.name for f in gdir.iterdir() if ".bak-" in f.name)

    with glossary_lock.locked(str(p), "verify") as held:
        assert held is True
        status, payload = _post(gdir, p)

    assert (status, payload) == (503, {"error": "glossary busy"})
    assert p.read_bytes() == before
    assert sorted(f.name for f in gdir.iterdir() if ".bak-" in f.name) == backups


def test_lock_yielding_false_is_503(gdir, monkeypatch):
    import contextlib

    p = _put(gdir)

    @contextlib.contextmanager
    def never(*a, **k):
        yield False

    monkeypatch.setattr(glossary_lock, "locked", never)
    assert _post(gdir, p)[0] == 503


def test_write_uses_the_webui_stage_name(gdir, monkeypatch):
    import contextlib

    p = _put(gdir)
    seen = []
    real = glossary_lock.locked

    @contextlib.contextmanager
    def spy(path, stage, *a, **k):
        seen.append((path, stage))
        with real(path, stage, *a, **k) as ok:
            yield ok

    monkeypatch.setattr(glossary_lock, "locked", spy)
    _post(gdir, p)
    assert seen == [(str(p), "webui")]


def test_failed_replace_leaves_the_original_and_no_temp(gdir, monkeypatch):
    p = _put(gdir)
    before = p.read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    status, payload = _post(gdir, p)
    assert status == 500 and "error" in payload
    assert p.read_bytes() == before
    assert sorted(f.name for f in gdir.iterdir() if f.name != f"{SHOW}.json.lock") != []
    assert not [f for f in gdir.iterdir() if f.name.endswith(".tmp")], "temp file cleaned up"


# --- validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        dict(op="frobnicate"),
        dict(key="verified"),
        dict(key="_curated"),
        dict(key="show"),
        dict(term=""),
        dict(term="   "),
        dict(term=5),
        dict(term=None),
        dict(term="bad\x00name"),
        dict(term="new\nline"),
        dict(term="x" * 81),  # names max 80
        dict(term="Luffy"),  # add duplicate
        dict(expected_version=None),
        dict(expected_version=3),
        dict(op="update", term="Ghost", value="Spirit"),  # absent
        dict(op="update", term="Zoro", value=""),
        dict(op="update", term="Zoro", value=None),
        dict(op="update", term="Zoro", value="Zoro"),  # rename to itself
        dict(op="update", term="Zoro", value="Luffy"),  # rename onto an existing name
        dict(op="delete", term="Ghost"),
    ],
)
def test_invalid_names_payloads_are_400_and_write_nothing(gdir, kw):
    p = _put(gdir)
    before = p.read_bytes()
    status, payload = _post(gdir, p, **kw)
    assert status == 400, payload
    assert "error" in payload
    assert p.read_bytes() == before
    assert [f for f in gdir.iterdir() if ".bak-" in f.name] == []


@pytest.mark.parametrize(
    "kw",
    [
        dict(term="OnePhrase"),  # phrases need a space
        dict(term="x y" + "z" * 120),  # > 120
        dict(term="Straw Hat Pirates"),  # duplicate
    ],
)
def test_invalid_phrases_are_400(gdir, kw):
    p = _put(gdir)
    assert _post(gdir, p, key="phrases", **kw)[0] == 400


@pytest.mark.parametrize(
    "kw",
    [
        dict(term="zorro", value=None),
        dict(term="zorro", value=""),
        dict(term="zorro", value="x" * 121),
        dict(term="x" * 121, value="Zoro"),
        dict(term="Zorro", value="zorro"),  # key == value case-insensitively
        dict(term="LUFI", value="Luffy"),  # case-insensitive duplicate of 'lufi'
        dict(term="a\x07b", value="Zoro"),
    ],
)
def test_invalid_hard_fixes_are_400(gdir, kw):
    p = _put(gdir)
    before = p.read_bytes()
    assert _post(gdir, p, key="hard_fixes", **kw)[0] == 400
    assert p.read_bytes() == before


def test_hard_fix_update_and_delete_match_keys_case_insensitively(gdir):
    p = _put(gdir)
    assert _post(gdir, p, key="hard_fixes", op="update", term="LUFI", value="Luffy-san")[0] == 200
    assert _disk(p)["hard_fixes"]["lufi"] == "Luffy-san"
    assert _post(gdir, p, key="hard_fixes", op="delete", term="LUFI")[0] == 200
    assert "lufi" not in _disk(p)["hard_fixes"]


def test_terms_are_trimmed(gdir):
    p = _put(gdir)
    _post(gdir, p, term="  Nami \t")
    assert "Nami" in _disk(p)["names"]


def test_non_dict_body_is_400(gdir):
    assert review_glossary.handle("POST", "/api/glossary", ["x"])[0] == 400


def _padded(n_fields):
    return {f"pad{i}": "short valid value" for i in range(n_fields)}


def test_a_body_over_64_kib_is_413_even_when_every_field_is_valid(gdir):
    p = _put(gdir)
    before = p.read_bytes()
    status, payload = _post(gdir, p, **_padded(4000))  # a valid request plus ~100 KiB of short extras
    assert (status, payload) == (413, {"error": "body too large"})
    assert p.read_bytes() == before


def test_the_body_cap_counts_utf8_bytes_not_escaped_characters(gdir):
    p = _put(gdir)
    # 25 000 two-byte characters = 50 000 bytes: under the cap, though escaped as \\uXXXX it would not be
    assert _post(gdir, p, pad="é" * 25000)[0] == 200
    # 30 000 three-byte characters = 90 000 bytes: over it
    assert _post(gdir, p, term="Sanji", expected_version=_version(p), pad="あ" * 30000)[0] == 413


def test_missing_editable_key_is_created_on_add(gdir):
    p = _put(gdir, data={"show": SHOW, "verified": {}})
    assert _post(gdir, p, key="phrases", term="Going Merry")[0] == 200
    assert _disk(p)["phrases"] == ["Going Merry"]


# --- audit -------------------------------------------------------------------------------


def test_each_write_logs_one_audit_line(gdir, capsys):
    p = _put(gdir)
    review_glossary.handle(
        "POST",
        "/api/glossary",
        {"show": SHOW, "op": "add", "key": "names", "term": "Nami", "expected_version": _version(p)},
        operator="token",
    )
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "glossary edit" in ln]
    assert len(lines) == 1
    for part in ("operator=token", f"show={json.dumps(SHOW)}", "op=add", "key=names", 'term="Nami"'):
        assert part in lines[0]


def test_refused_writes_log_no_audit_line(gdir, capsys):
    p = _put(gdir)
    _post(gdir, p, expected_version="0" * 64)
    assert "glossary edit" not in capsys.readouterr().out


def test_audit_line_cannot_be_forged_by_a_term(gdir, capsys):
    p = _put(gdir)
    _post(gdir, p, term="Nami\nglossary edit: operator=admin")
    assert len([ln for ln in capsys.readouterr().out.splitlines() if "glossary edit" in ln]) == 0  # 400: control char


# --- routes ------------------------------------------------------------------------------


def test_routes_are_token_gated_and_delegate(gdir, tmp_path, monkeypatch):
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "_GENERATED", None)  # restored on teardown: no leak into test_review_server
    tok = review_server.resolve_token(str(tmp_path))
    p = _put(gdir)

    assert review_server.route("GET", "/api/glossary", {}, None)[0] == 401
    assert review_server.route("POST", "/api/glossary", {}, "nope")[0] == 401
    assert review_server.route("GET", "/api/glossary", {}, tok) == (200, {"shows": [SHOW]})
    status, payload = review_server.route(
        "POST",
        "/api/glossary",
        {"show": SHOW, "op": "add", "key": "names", "term": "Nami", "expected_version": _version(p)},
        tok,
    )
    assert status == 200 and payload["reapply_hint"] is True


def test_audit_operator_is_token_when_auth_on_and_anonymous_when_off(gdir, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "_GENERATED", None)  # restored on teardown: no leak into test_review_server
    tok = review_server.resolve_token(str(tmp_path))
    p = _put(gdir)

    review_server.route(
        "POST",
        "/api/glossary",
        {"show": SHOW, "op": "add", "key": "names", "term": "Nami", "expected_version": _version(p)},
        tok,
    )
    monkeypatch.setenv("REVIEW_AUTH", "off")
    review_server.route(
        "POST",
        "/api/glossary",
        {"show": SHOW, "op": "add", "key": "names", "term": "Sanji", "expected_version": _version(p)},
        None,
        headers={"X-DubTitlerr-Request": "1"},
    )
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "glossary edit" in ln]
    assert "operator=token" in lines[0] and "operator=anonymous" in lines[1]


def test_open_routes_is_unchanged():
    assert not any("glossary" in route for _method, route in review_server.OPEN_ROUTES)
    assert set(review_server.OPEN_ROUTES) == {
        ("GET", "/healthz"),
        ("GET", "/api/auth-mode"),
        ("POST", "/api/login"),
        ("POST", "/api/setup"),
    }


# --- fix round: separators, normalization, symlinks, sidecars, failed prune --------------


@pytest.mark.parametrize(
    "char",
    [" ", " ", "​", "‮", "﻿", "", "\ud800", "\x85"],
    ids=["LS", "PS", "ZWSP", "RLO", "BOM", "private-use", "surrogate", "NEL"],
)
def test_separators_format_controls_and_private_use_are_refused(gdir, capsys, char):
    p = _put(gdir)
    before = p.read_bytes()
    assert _post(gdir, p, term=f"Nami{char}glossary edit: operator=admin")[0] == 400
    assert _post(gdir, p, term=f"Na{char}mi")[0] == 400
    assert _post(gdir, p, key="hard_fixes", term="zorro", value=f"Zo{char}ro")[0] == 400
    assert p.read_bytes() == before
    assert "glossary edit" not in capsys.readouterr().out


def test_a_plain_inner_space_is_still_allowed(gdir):
    p = _put(gdir)
    assert _post(gdir, p, key="phrases", term="Going Merry")[0] == 200


def test_a_nfd_term_is_a_duplicate_of_its_nfc_entry(gdir):
    p = _put(gdir, data={**RAW, "names": ["Café"]})
    before = p.read_bytes()
    assert _post(gdir, p, term="Café")[0] == 400
    assert p.read_bytes() == before


def test_a_nfd_term_finds_its_nfc_entry_to_update_and_delete(gdir):
    p = _put(gdir, data={**RAW, "names": ["Café", "Zoro"]})
    assert _post(gdir, p, op="update", term="Café", value="Café Noir")[0] == 200
    assert _disk(p)["names"] == ["Café Noir", "Zoro"], "the value is stored NFC"
    assert _post(gdir, p, op="delete", term="Café Noir")[0] == 200
    assert _disk(p)["names"] == ["Zoro"]


def test_a_nfc_term_finds_an_entry_stored_nfd(gdir):
    p = _put(gdir, data={**RAW, "names": ["Café", "Zoro"]})
    assert _post(gdir, p, term="Café")[0] == 400
    assert _post(gdir, p, op="delete", term="Café")[0] == 200
    assert _disk(p)["names"] == ["Zoro"]


def test_entries_the_operator_did_not_touch_are_never_renormalized(gdir):
    p = _put(gdir, data={**RAW, "names": ["Café", "Zoro"], "hard_fixes": {"café": "Cafe"}})
    _post(gdir, p, term="Nami")
    disk = _disk(p)
    assert disk["names"][0] == "Café", "stored NFD entry stays NFD"
    assert "café" in disk["hard_fixes"]


def test_hard_fix_keys_compare_nfc_folded(gdir):
    p = _put(gdir, data={**RAW, "hard_fixes": {"café": "Cafe"}})
    assert _post(gdir, p, key="hard_fixes", term="CAFÉ", value="Coffee")[0] == 400
    assert _post(gdir, p, key="hard_fixes", op="delete", term="Café")[0] == 200
    assert _disk(p)["hard_fixes"] == {}


def test_a_symlinked_json_is_not_a_glossary(gdir, tmp_path):
    _put(gdir)
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"names": ["leak"]}))
    (gdir / "secret.json").symlink_to(secret)
    inside = gdir / "alias.json"
    inside.symlink_to(gdir / f"{SHOW}.json")
    (gdir / "dir.json").mkdir()

    assert review_glossary.handle("GET", "/api/glossary", {})[1] == {"shows": [SHOW]}
    for name in ("secret", "alias", "dir"):
        assert review_glossary.handle("GET", "/api/glossary", {"show": name}) == (404, {"error": "no such glossary"})
        assert _post(gdir, gdir / f"{SHOW}.json", show=name)[0] == 404
    assert json.loads(secret.read_text()) == {"names": ["leak"]}


def test_a_glossary_swapped_for_a_symlink_after_listing_is_not_read(gdir, tmp_path, monkeypatch):
    p = _put(gdir)
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"names": ["leak"]}))
    monkeypatch.setattr(review_glossary, "list_shows", lambda gdir=None: [SHOW])  # the race: listed, then swapped
    p.unlink()
    p.symlink_to(secret)
    status, payload = review_glossary.handle("GET", "/api/glossary", {"show": SHOW})
    assert status != 200 and "names" not in payload


@pytest.mark.parametrize("junk", ["One Pace.journal.json", "One Pace.lastrun.json", "One Pace.acquire-cache.json"])
def test_sidecar_json_files_are_not_glossaries(gdir, junk):
    _put(gdir)
    (gdir / junk).write_text("{}")
    assert review_glossary.handle("GET", "/api/glossary", {})[1] == {"shows": [SHOW]}
    assert review_glossary.handle("GET", "/api/glossary", {"show": junk[:-5]})[0] == 404


def test_a_failing_prune_after_the_swap_is_still_a_200_with_an_audit_line(gdir, monkeypatch, capsys):
    p = _put(gdir)

    def boom(*a, **k):
        raise OSError("listdir failed")

    monkeypatch.setattr(review_glossary, "prune_backups", boom)
    status, payload = _post(gdir, p)
    assert status == 200 and payload["ok"] is True, "the file was already replaced; reporting failure would be a lie"
    assert "Nami" in _disk(p)["names"]
    assert len([ln for ln in capsys.readouterr().out.splitlines() if "glossary edit" in ln]) == 1


# --- review round: literal replacement values, audit, shape checks, durability -----------


@pytest.mark.parametrize("value", ["AC\\DC", "\\g<0>x", "\\1", "a\\\\b"], ids=["backslash-D", "g0", "group-ref", "double"])
def test_a_hard_fix_value_is_inserted_literally_by_correct(gdir, value):
    import glossary

    p = _put(gdir)
    assert _post(gdir, p, key="hard_fixes", term="acdc band", value=value)[0] == 200
    loaded = glossary.load_dict(_disk(p))

    out, n = glossary.correct("I like the ACDC band a lot", loaded)
    assert (out, n) == (f"I like the {value} a lot", 1)
    # and lines that do not contain the key are untouched rather than raising
    assert glossary.correct("nothing here", loaded) == ("nothing here", 0)


def test_correct_takes_a_hand_written_template_looking_value_literally():
    import glossary

    gloss = glossary.load_dict({"hard_fixes": {"two words": "A\\DC \\g<0>"}})
    assert glossary.correct("say two words now", gloss) == ("say A\\DC \\g<0> now", 1)


def test_the_audit_line_carries_time_the_stored_term_and_the_update_value(gdir, capsys):
    p = _put(gdir, data={**RAW, "names": ["Caf\u00e9"]})
    review_glossary.handle(
        "POST",
        "/api/glossary",
        {
            "show": SHOW,
            "op": "update",
            "key": "names",
            "term": "Cafe\u0301",
            "value": "Cafe\u0301 Noir",
            "expected_version": _version(p),
        },
        operator="token",
    )
    (line,) = [ln for ln in capsys.readouterr().out.splitlines() if "glossary edit" in ln]
    import re

    assert re.search(r" at=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z) ", line), line
    assert 'term="Caf\u00e9"' in line, "the validated NFC term, not the raw input"
    assert 'value="Caf\u00e9 Noir"' in line


def test_an_add_logs_no_value_field(gdir, capsys):
    p = _put(gdir)
    _post(gdir, p)
    (line,) = [ln for ln in capsys.readouterr().out.splitlines() if "glossary edit" in ln]
    assert " value=" not in line


@pytest.mark.parametrize(
    "patch",
    [{"names": "Luffy Zoro"}, {"phrases": {"a": 1}}, {"hard_fixes": "x"}, {"hard_fixes": [["a", "b"]]}, {"names": 5}],
    ids=["names-str", "phrases-dict", "hard_fixes-str", "hard_fixes-pairs", "names-int"],
)
def test_wrong_typed_editable_keys_are_corrupt_not_rewritten(gdir, patch):
    p = _put(gdir, data={**RAW, **patch})
    before = p.read_bytes()
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW}) == (500, {"error": "glossary corrupt"})
    status, payload = _post(gdir, p, expected_version=_version(p))
    assert (status, payload) == (500, {"error": "glossary corrupt"})
    assert p.read_bytes() == before
    assert [f for f in gdir.iterdir() if ".bak-" in f.name] == []


def test_null_editable_keys_still_read_as_empty(gdir):
    _put(gdir, data={"show": SHOW, "names": None, "hard_fixes": None})
    _, payload = review_glossary.handle("GET", "/api/glossary", {"show": SHOW})
    assert payload["names"] == [] and payload["hard_fixes"] == {}


def test_a_failed_write_leaves_no_backup_behind(gdir, monkeypatch):
    p = _put(gdir)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert _post(gdir, p)[0] == 500
    assert [f.name for f in gdir.iterdir() if ".bak-" in f.name] == [], "a failed edit must not pile up undo files"


def test_the_directory_is_fsynced_after_the_rename(gdir, monkeypatch):
    import stat

    p = _put(gdir)
    events = []
    real_replace, real_fsync = os.replace, os.fsync

    def replace(*a, **k):
        events.append("replace")
        return real_replace(*a, **k)

    def fsync(fd):
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        return real_fsync(fd)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "fsync", fsync)
    assert _post(gdir, p)[0] == 200
    assert events[-2:] == ["replace", "fsync-dir"], events


def test_a_failing_directory_fsync_does_not_fail_a_committed_edit(gdir, monkeypatch):
    import stat

    p = _put(gdir)
    real = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("not supported")
        return real(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    status, _ = _post(gdir, p)
    assert status == 200 and "Nami" in _disk(p)["names"]


def test_an_edit_made_while_the_post_waits_for_the_lock_is_a_409(gdir, monkeypatch):
    """A real contention test: the POST blocks on the held lock, the file changes meanwhile, and the
    version check must see the file as it is once the lock is won -- not as it was before waiting."""
    import threading
    import time

    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "10")
    p = _put(gdir)
    v0 = _version(p)
    result = {}

    def post():
        result["r"] = _post(gdir, p, term="Mine", expected_version=v0)

    with glossary_lock.locked(str(p), "other-stage") as held:
        assert held is True
        t = threading.Thread(target=post)
        t.start()
        time.sleep(0.4)  # the POST is now waiting on the lock
        assert "r" not in result
        p.write_text(json.dumps({**RAW, "names": ["Someone else's edit"]}, indent=2) + "\n")
    t.join(timeout=15)

    assert result["r"][0] == 409, result
    assert _disk(p)["names"] == ["Someone else's edit"]
    assert [f for f in gdir.iterdir() if ".bak-" in f.name] == []


def test_the_file_mode_is_preserved(gdir):
    import stat

    p = _put(gdir)
    p.chmod(0o640)
    _post(gdir, p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o640


def test_two_writes_in_the_same_clock_tick_keep_distinct_backups(gdir, monkeypatch):
    import datetime as real_dt

    class FrozenDatetime(real_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 12, 12, 0, 0, 0, tzinfo=tz)

    class FrozenModule:
        datetime = FrozenDatetime
        timezone = real_dt.timezone

    monkeypatch.setattr(review_glossary, "datetime", FrozenModule)
    p = _put(gdir)
    first_bytes = p.read_bytes()
    _, one = _post(gdir, p, term="One")
    second_bytes = p.read_bytes()
    _, two = _post(gdir, p, term="Two", expected_version=one["version"])

    assert one["backup"] != two["backup"]
    assert (gdir / one["backup"]).read_bytes() == first_bytes
    assert (gdir / two["backup"]).read_bytes() == second_bytes
    names = sorted(f.name for f in gdir.iterdir() if ".bak-" in f.name)
    assert names.index(one["backup"]) < names.index(two["backup"]), "later backup sorts later, so prune keeps it"


# --- backslashes: refused in names and phrases, kept literal in hard-fix values -----------


@pytest.mark.parametrize("key, term", [("names", "AC\\DC"), ("phrases", "AC\\DC band")])
def test_a_backslash_is_refused_in_names_and_phrases(gdir, key, term):
    p = _put(gdir)
    before = p.read_bytes()
    status, payload = _post(gdir, p, key=key, term=term)
    assert status == 400 and "backslash" in payload["error"]
    assert p.read_bytes() == before


def test_a_backslash_is_refused_in_a_rename_value(gdir):
    p = _put(gdir)
    status, payload = _post(gdir, p, op="update", term="Zoro", value="Zo\\ro")
    assert status == 400 and "backslash" in payload["error"]


def test_a_backslash_in_a_hard_fix_value_is_still_allowed(gdir):
    p = _put(gdir)
    assert _post(gdir, p, key="hard_fixes", term="acdc band", value="AC\\DC")[0] == 200
