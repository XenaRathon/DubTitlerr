import json
import stat

import pytest

import glossary_lock
import review_auth

pytestmark = pytest.mark.real_accounts


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)  # fast hashes; the format test in Task 1 pins the real cost
    return tmp_path


def test_create_user_writes_a_0600_file_with_a_scrypt_hash_and_never_the_password(cfg):
    review_auth.create_user("Alice", "admin", "s3cret-passphrase")
    path = cfg / "users.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = path.read_text()
    assert "s3cret-passphrase" not in raw and '"scrypt$' in raw
    doc = json.loads(raw)
    row = doc["users"][0]
    assert doc["version"] == 1 and (row["name"], row["role"]) == ("Alice", "admin")
    assert isinstance(row["pw_changed_at"], float) and row["session_epoch"] == 0
    assert review_auth.verify_password("s3cret-passphrase", row["hash"])


def test_a_missing_file_means_no_accounts_and_setup_is_required(cfg):
    assert review_auth.read_users() == [] and review_auth.setup_required() is True
    review_auth.create_user("alice", "user", "long enough pw")
    assert review_auth.setup_required() is False


def test_usernames_are_unique_case_insensitively(cfg):
    review_auth.create_user("Alice", "user", "long enough pw")
    with pytest.raises(review_auth.Conflict) as e:
        review_auth.create_user("ALICE", "user", "long enough pw")
    assert (e.value.status, e.value.message) == (409, "username taken")
    assert review_auth.find_user(review_auth.read_users(), "aLiCe")["name"] == "Alice"


def test_invalid_input_is_refused_before_anything_is_written(cfg):
    for args in [("bad name", "user", "long enough pw"), ("bob", "root", "long enough pw"), ("bob", "user", "short")]:
        with pytest.raises(review_auth.Invalid):
            review_auth.create_user(*args)
    assert not (cfg / "users.json").exists()


def test_only_if_empty_refuses_a_second_first_admin(cfg):
    review_auth.create_user("first", "admin", "long enough pw", only_if_empty=True)
    with pytest.raises(review_auth.Conflict) as e:
        review_auth.create_user("second", "admin", "long enough pw", only_if_empty=True)
    assert (e.value.status, e.value.message) == (409, "already set up")


def test_a_corrupt_file_is_unreadable_never_empty_and_is_left_untouched(cfg):
    (cfg / "users.json").write_text("{not json")
    with pytest.raises(review_auth.Unreadable):
        review_auth.read_users()
    assert review_auth.setup_required() is False, "corrupt is not first run: nobody may claim the instance"
    with pytest.raises(review_auth.Unreadable):
        review_auth.create_user("x", "admin", "long enough pw")
    assert (cfg / "users.json").read_text() == "{not json"


def test_a_well_formed_file_of_the_wrong_shape_is_unreadable(cfg):
    (cfg / "users.json").write_text('{"version": 1, "users": [{"name": "a"}]}')
    with pytest.raises(review_auth.Unreadable):
        review_auth.read_users()


def test_a_busy_lock_is_a_503_busy_and_writes_nothing(cfg, monkeypatch):
    monkeypatch.setattr(review_auth, "LOCK_WAIT", 0.05)
    with glossary_lock.locked(str(cfg / "users.json"), "holder", wait=0):
        with pytest.raises(review_auth.Busy) as e:
            review_auth.create_user("a", "admin", "long enough pw")
    assert (e.value.status, e.value.message) == (503, "busy, try again")
    assert not (cfg / "users.json").exists()


def test_a_read_only_volume_is_a_503_and_leaves_no_half_written_file(cfg, monkeypatch):
    review_auth.create_user("alice", "admin", "long enough pw")
    before = (cfg / "users.json").read_bytes()

    def refuse(*a, **k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(review_auth.os, "replace", refuse)
    with pytest.raises(review_auth.Unavailable) as e:
        review_auth.create_user("bob", "user", "long enough pw")
    assert e.value.status == 503
    assert (cfg / "users.json").read_bytes() == before
    assert [p.name for p in cfg.iterdir() if p.name.endswith(".tmp")] == []
