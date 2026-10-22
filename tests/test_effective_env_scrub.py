"""[S-7] The effective-env reports (effective.env, merge-effective.env) never carry a secret or a URL's user info; mode 0640."""

import os
import stat

import review_requests as rr

TOKEN = "plex-token-5d2f9c71aa80"
KEY = "sk-hosted-key-0123456789abcdef"


def written(tmp_path, env):
    path = tmp_path / "report.env"
    rr.write_effective_env(str(path), env)
    return path, path.read_text()


def test_every_generate_and_merge_registry_key_is_reported_not_only_the_old_allow_list(tmp_path):
    _, text = written(
        tmp_path,
        {"WHISPER_BEAM_SIZE": "5", "MINE_MIN_COUNT": "4", "KEEP_LANGS": "eng,und", "REVIEW_PORT": "9000", "CONFIG_DIR": "/x"},
    )
    assert text == "KEEP_LANGS=eng,und\nMINE_MIN_COUNT=4\nWHISPER_BEAM_SIZE=5\n", (
        "server and container keys are not builder state"
    )


def test_registry_secrets_and_key_holders_are_never_reported(tmp_path):
    path, text = written(
        tmp_path,
        {
            "PLEX_TOKEN": TOKEN,
            "WATCHSTATE_API_KEY": "ws-api-key-abcdef123456",  # gitleaks:allow -- test fixture, not a real credential
            "DT_CONN_KEY_REPAIR": KEY,
            "GITHUB_PAT": "ghp_abcdefghijklmnop",
            "WHISPER_BEAM_SIZE": "5",
        },
    )
    assert text == "WHISPER_BEAM_SIZE=5\n"


def test_user_info_is_stripped_from_urls_not_the_whole_line_dropped(tmp_path):
    _, text = written(
        tmp_path,
        {
            "PLEX_URL": "http://admin:hunter22@plex.lan:32400/web",
            "REPAIR_OPENAI_URL": "https://sk-token-xyz123@api.example.test/v1",
        },
    )
    assert "PLEX_URL=http://plex.lan:32400/web\n" in text and "REPAIR_OPENAI_URL=https://api.example.test/v1\n" in text
    assert "hunter22" not in text and "admin" not in text and "sk-token-xyz123" not in text


def test_user_info_with_raw_at_in_password_is_stripped_cleanly(tmp_path):
    _, text = written(
        tmp_path,
        {
            "PLEX_URL": "http://user:p@ssword@plex.lan:32400/web",
        },
    )
    assert text == "PLEX_URL=http://plex.lan:32400/web\n"
    assert "p@ssword" not in text and "user" not in text


def test_a_secret_value_repeated_in_another_variable_drops_that_line(tmp_path):
    _, text = written(tmp_path, {"PLEX_TOKEN": TOKEN, "PLEX_PATH": f"/library?X-Plex-Token={TOKEN}", "PLEX_SECTION": "7"})
    assert text == "PLEX_SECTION=7\n"


def test_the_existing_key_shaped_value_and_extra_body_rules_still_hold(tmp_path):
    _, text = written(
        tmp_path, {"REPAIR_MODEL": "sk-0123456789abcdefghij", "REPAIR_EXTRA_BODY": "{}", "REPAIR_BACKEND": "llamacpp"}
    )
    assert text == "REPAIR_BACKEND=llamacpp\n"


def test_the_report_is_mode_0640_whatever_the_umask(tmp_path):
    old = os.umask(0o000)
    try:
        path, _ = written(tmp_path, {"WHISPER_BEAM_SIZE": "5"})
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640
