import hashlib
import json
import stat
import time

import pytest

import glossary_lock
import review_auth

pytestmark = pytest.mark.real_accounts
DAY = 86400.0


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def store(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(review_auth, "CLOCK", clock)
    monkeypatch.setattr(review_auth, "LOCK_WAIT", 0.05)
    s = review_auth.SessionStore(str(tmp_path / "sessions.json"))
    s.clock = clock
    s.file = tmp_path / "sessions.json"
    return s


def rows(s):
    return json.loads(s.file.read_text())["sessions"]


def test_a_session_is_stored_only_as_a_sha256_in_a_0600_file(store):
    sid = store.create("alice", True)
    raw = store.file.read_text()
    assert sid not in raw and len(sid) >= 43
    assert stat.S_IMODE(store.file.stat().st_mode) == 0o600
    (row,) = rows(store)
    assert set(row) == {"id_sha256", "name", "created", "last_seen", "remember", "epoch"}
    assert row["id_sha256"] == hashlib.sha256(sid.encode()).hexdigest()


def test_the_account_epoch_is_stored_with_the_session_and_survives_a_restart(store):
    sid = store.create("alice", True, epoch=3)
    assert store.lookup(sid).epoch == 3 and rows(store)[0]["epoch"] == 3
    assert review_auth.SessionStore(str(store.file)).lookup(sid).epoch == 3


def test_every_create_issues_a_new_id(store):
    a, b = store.create("alice", False), store.create("alice", False)
    assert a != b and store.lookup(a).name == "alice" and store.lookup(b).name == "alice"


def test_unknown_and_non_string_ids_are_not_sessions(store):
    store.create("alice", True)
    assert store.lookup("nope") is None and store.lookup("") is None and store.lookup(None) is None


def test_a_remember_me_session_survives_29_days_of_activity_and_dies_after_31_idle_days(store):
    sid = store.create("alice", True)
    for _ in range(29):
        store.clock.now += DAY
        assert store.lookup(sid).name == "alice"
    store.clock.now += 31 * DAY
    assert store.lookup(sid) is None


def test_the_remember_limit_is_exactly_30_idle_days(store):
    sid = store.create("alice", True)
    store.clock.now += 30 * DAY
    assert store.lookup(sid) is not None
    store.clock.now += 30 * DAY + 1
    assert store.lookup(sid) is None


def test_a_browser_session_has_a_12_hour_idle_limit(store):
    sid = store.create("alice", False)
    store.clock.now += 11 * 3600
    assert store.lookup(sid) is not None
    store.clock.now += 13 * 3600
    assert store.lookup(sid) is None


def test_a_clock_that_jumps_backwards_does_not_extend_or_kill_a_session(store):
    sid = store.create("alice", False)
    store.clock.now -= 10 * DAY
    assert store.lookup(sid) is not None
    store.clock.now += 10 * DAY + 13 * 3600
    assert store.lookup(sid) is None


def test_last_seen_is_flushed_at_most_every_ten_minutes(store):
    sid = store.create("alice", True)
    created = rows(store)[0]["last_seen"]
    store.clock.now += 300
    store.lookup(sid)
    assert rows(store)[0]["last_seen"] == created
    store.clock.now += 301
    store.lookup(sid)
    assert rows(store)[0]["last_seen"] == store.clock.now


def test_a_failed_flush_is_logged_and_never_fails_the_request(store, monkeypatch, capsys):
    sid = store.create("alice", True)

    def refuse(*a, **k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(review_auth.os, "replace", refuse)
    store.clock.now += 601
    assert store.lookup(sid).name == "alice"
    assert "could not flush sessions" in capsys.readouterr().out
    store.clock.now += 5
    assert store.lookup(sid).name == "alice"
    assert "could not flush sessions" not in capsys.readouterr().out, "no retry storm: the next flush waits another interval"


def test_a_busy_sessions_lock_neither_slows_nor_fails_a_lookup(store):
    sid = store.create("alice", True)
    store.clock.now += 601
    with glossary_lock.locked(str(store.file), "someone-else", wait=0):
        started = time.monotonic()
        assert store.lookup(sid).name == "alice"
        assert time.monotonic() - started < 1.0


def test_sessions_survive_a_restart(store):
    sid = store.create("alice", True)
    assert review_auth.SessionStore(str(store.file)).lookup(sid).name == "alice"


def test_expired_sessions_are_pruned_when_the_file_is_written(store):
    store.create("old", False)
    store.clock.now += 40 * DAY
    store.create("new", False)
    assert [r["name"] for r in rows(store)] == ["new"]


def test_revoke_and_revoke_user(store):
    a, b, c = store.create("alice", True), store.create("ALICE", True), store.create("bob", True)
    store.revoke(c)
    assert store.lookup(c) is None
    assert store.revoke_user("alice", keep_sid=a) == 1
    assert store.lookup(a) is not None and store.lookup(b) is None
    assert store.revoke_user("alice") == 1 and store.lookup(a) is None
    assert rows(store) == []


def test_a_remember_me_cookie_is_refreshed_once_a_day_and_a_browser_session_never(store):
    r, b = store.create("alice", True), store.create("alice", False)
    store.clock.now += 3600
    assert store.lookup(r).refresh is False and store.lookup(b).refresh is False
    for _ in range(3):  # 33 more hours in steps inside the 12 h idle limit, so the browser session stays alive and is checked
        store.clock.now += 11 * 3600
        assert store.lookup(b).refresh is False
    assert store.lookup(r).refresh is True
    assert store.lookup(r).refresh is False
    assert store.lookup(b).refresh is False


def test_a_failed_create_leaves_nothing_behind(store, monkeypatch):
    def refuse(*a, **k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(review_auth.os, "replace", refuse)
    with pytest.raises(review_auth.Unavailable):
        store.create("alice", True)
    assert store.lookup("anything") is None and not store.file.exists()


def test_sessions_returns_one_store_per_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "a"))
    first = review_auth.sessions()
    assert review_auth.sessions() is first
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "b"))
    assert review_auth.sessions() is not first
