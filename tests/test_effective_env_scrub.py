"""[S-7] The effective-env reports (effective.env, merge-effective.env) never carry a secret or a URL's user info; mode 0640."""

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
