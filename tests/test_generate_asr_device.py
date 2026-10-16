"""[S-13] ASR_DEVICE is a first-wave setting, so generate.py must actually read it. Parsed, never imported: generate.py loads
faster_whisper at module level."""

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = ast.parse(open(os.path.join(ROOT, "generate.py"), encoding="utf-8").read())


def test_generate_reads_asr_device_from_the_environment_with_a_cuda_default():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ASR_DEVICE" for t in node.targets):
            call = node.value
            assert isinstance(call, ast.Call) and [a.value for a in call.args if isinstance(a, ast.Constant)] == [
                "ASR_DEVICE",
                "cuda",
            ]
            return
    raise AssertionError("generate.py does not assign ASR_DEVICE from the environment")


def test_the_whisper_model_is_loaded_on_that_device_not_a_literal():
    devices = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "WhisperModel":
            devices += [kw.value for kw in node.keywords if kw.arg == "device"]
    assert devices and all(isinstance(d, ast.Name) and d.id == "ASR_DEVICE" for d in devices)
