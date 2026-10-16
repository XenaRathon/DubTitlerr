import pytest

import review_auth
import review_server as rs

pytestmark = pytest.mark.real_accounts


def test_a_user_can_post_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    review_auth.create_user("root", "admin", "admin password")
    review_auth.create_user("alice", "user", "user password!")
    sid = review_auth.sessions().create("alice", False)
    headers = {"Cookie": f"dubtitlerr_session={sid}", "X-DubTitlerr-Request": "1"}
    assert review_auth.ROUTE_ROLES[("POST", "/api/apply")] == "user"
    assert rs.route("POST", "/api/apply", {"stem": "no-such-stem"}, None, headers=headers) == (200, {"error": "unknown episode"})
