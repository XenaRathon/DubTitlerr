import os

PRESET = os.environ.get("CONFIG_DIR")  # what the shell or CI had set before any fixture ran


def test_the_suite_never_runs_against_a_config_dir_from_the_environment(tmp_path_factory):
    now = os.environ["CONFIG_DIR"]
    assert now != PRESET, "the autouse fixture must replace a CONFIG_DIR the shell already set"
    assert os.path.realpath(now).startswith(os.path.realpath(str(tmp_path_factory.getbasetemp())))
