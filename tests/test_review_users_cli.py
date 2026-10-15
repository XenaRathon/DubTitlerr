import json

import pytest

import glossary_lock
import review_auth
import review_users

pytestmark = pytest.mark.real_accounts


class Clock:
    def __init__(self, now=2_000_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    clock = Clock()
    monkeypatch.setattr(review_auth, "CLOCK", clock)
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    review_auth.create_user("root", "admin", "forgotten password")
    review_auth.create_user("alice", "user", "alice password")
    return clock


def password_from(out):
    line = next(ln for ln in out.splitlines() if ln.startswith("New one-time password for"))
    return line.rsplit(": ", 1)[1]


def test_reset_admin_prints_a_working_one_time_password_and_ends_the_sessions(env, capsys):
    sid = review_auth.sessions().create("root", True)
    env.now += 5
    assert review_users.main(["reset-admin", "ROOT"]) == 0
    new = password_from(capsys.readouterr().out)
    assert len(new) >= 10 and review_auth.validate_password(new) is None
    row = review_auth.find_user(review_auth.read_users(), "root")
    assert review_auth.verify_password(new, row["hash"])
    assert not review_auth.verify_password("forgotten password", row["hash"])
    assert review_auth.sessions().lookup(sid) is None


def test_the_old_cookie_is_refused_after_a_reset(env, capsys):
    sid = review_auth.sessions().create("root", True)
    cookie = {"Cookie": f"dubtitlerr_session={sid}"}
    assert review_auth.role_for("GET", "/api/episodes", cookie) == ("admin", None)
    env.now += 5
    review_users.main(["reset-admin", "root"])
    assert review_auth.role_for("GET", "/api/episodes", cookie) == (None, 401)


def test_the_password_is_printed_once_and_never_reaches_the_log(env, capsys):
    review_users.main(["reset-admin", "root"])
    out = capsys.readouterr().out
    assert out.count(password_from(out)) == 1


def test_an_unknown_account_is_exit_1_and_a_plain_user_is_exit_2(env, capsys):
    assert review_users.main(["reset-admin", "nobody"]) == 1
    assert review_users.main(["reset-admin", "alice"]) == 2
    err = capsys.readouterr().err
    assert "no account named nobody" in err and "not an admin" in err


def test_an_unreadable_accounts_file_is_set_aside_and_the_named_admin_is_created(env, tmp_path, capsys):
    (tmp_path / "users.json").write_text("{not json")
    sid = review_auth.sessions().create("rescue", True)
    assert review_users.main(["reset-admin", "rescue"]) == 0
    assert [p.name for p in tmp_path.glob("users.json.corrupt-*")]
    assert review_auth.find_user(review_auth.read_users(), "rescue")["role"] == "admin"
    assert json.loads((tmp_path / "users.json").read_text())["users"][0]["name"] == "rescue"
    assert review_auth.sessions().lookup(sid) is None
    assert "set aside" in capsys.readouterr().out


def test_invalid_username_leaves_unreadable_users_file_in_place(env, tmp_path, capsys):
    path = tmp_path / "users.json"
    path.write_text("{not json")
    assert review_users.main(["reset-admin", "bad name with spaces"]) == 1
    assert path.read_text() == "{not json"
    assert not list(tmp_path.glob("users.json.corrupt-*"))
    assert "username must be" in capsys.readouterr().err


def test_usage_errors_are_exit_2(env, capsys):
    with pytest.raises(SystemExit) as e:
        review_users.main([])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        review_users.main(["reset-admin"])
    assert e.value.code == 2


def test_lock_contention_returns_exit_1(env, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(review_auth, "LOCK_WAIT", 0.01)
    with glossary_lock.locked(review_auth.users_path(), "test_holder", wait=0):
        assert review_users.main(["reset-admin", "root"]) == 1
    assert "busy" in capsys.readouterr().err


def test_unreadable_accounts_file_under_lock_contention_returns_exit_1(env, tmp_path, capsys, monkeypatch):
    (tmp_path / "users.json").write_text("{not json")
    monkeypatch.setattr(review_auth, "LOCK_WAIT", 0.01)
    with glossary_lock.locked(review_auth.users_path(), "test_holder", wait=0):
        assert review_users.main(["reset-admin", "rescue"]) == 1
    assert (tmp_path / "users.json").read_text() == "{not json"
    assert not list(tmp_path.glob("users.json.corrupt-*"))
    assert "busy" in capsys.readouterr().err


def test_empty_users_file_seeds_admin_and_revokes_sessions(env, tmp_path, capsys):
    (tmp_path / "users.json").write_text(json.dumps({"version": 1, "users": []}))
    sid = review_auth.sessions().create("root", True)
    assert review_users.main(["reset-admin", "root"]) == 0
    assert review_auth.find_user(review_auth.read_users(), "root")["role"] == "admin"
    assert review_auth.sessions().lookup(sid) is None
