import review_server

RETIRED = ("X-Review-Token", "X-Review-Admin-Token", "dubtitlerr_token", "dubtitlerr_review_token")


def test_the_classic_pages_have_no_token_box_and_send_the_csrf_header_on_every_write(monkeypatch):
    monkeypatch.setattr(review_server, "known_stems", lambda: [])
    for page in (review_server.render_page(), review_server.render_shared()):
        assert page.count("fetch(") == 1
        assert "'X-DubTitlerr-Request':'1'" in page
        assert "id=tok" not in page and "TOK" not in page
        for name in RETIRED:
            assert name not in page, name


def test_a_401_is_still_surfaced_by_alert_on_both_pages(monkeypatch):
    monkeypatch.setattr(review_server, "known_stems", lambda: [])
    assert "if(r.error){alert(r.error)" in review_server.render_page()
    assert "if(r.error){alert(r.error)" in review_server.render_shared()


def test_the_locked_shell_offers_a_sign_in_link_and_nothing_to_type_a_token_into():
    for kind in ("page", "shared"):
        out = review_server.render_locked(kind)
        assert "needs-token" in out and "/review/login" in out
        for gone in ("id=tok", "<script", "fetch(", "localStorage") + RETIRED:
            assert gone not in out, gone
    assert "/review/setup" in review_server.render_locked("page", setup=True)
