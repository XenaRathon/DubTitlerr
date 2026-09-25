# Story: Fail-closed mux and shell crash classification

Status: done 2026-09-24
Epic: buffy-release-review-fixes
Sprint: -

## Description

Implement fail-closed validation outcomes and robust shell crash classification in mux and merge pass workflows to prevent silent data corruption or unhandled verification failures during subtitle processing.

## Acceptance Criteria

- [x] Valid `common.STAGE_OUTCOMES` records generated for verification failure, signs-refusal, and unexpected exception sanitization.
- [x] Apostrophe-safe `merge_pass.sh` fallback implemented to prevent syntax errors on stems containing quotes or apostrophes.
- [x] Comprehensive test coverage validating mux build errors and crashed record fallbacks.

## Evidence

### RED Evidence

Initial test execution failed as expected prior to implementing the fail-closed error mapping:

- `pytest -q tests/test_mux.py::test_process_records_verification_failure_as_mux_build_error tests/test_merge_pass.py::test_apostrophe_stem_records_real_crash_fallback` failed with `assert None == 'mux'` and missing crashed record; exit 1.
- Second RED pair failed with `AssertionError: assert None == 'build-error'` and `AssertionError: assert None == 'crashed'`; exit 1.

### GREEN Evidence

Focused main-based test execution:

- `pytest -o addopts='' --disable-warnings -q tests/test_mux.py tests/test_merge_pass.py` -> 60 passed, exit 0.
- Full test suite: `pytest -o addopts='' --disable-warnings -q tests` -> 1776 passed, exit 0.
- Shell syntax check: `bash -n merge_pass.sh` -> exit 0.

### Mutation Reasoning

Tests explicitly assert observable sidecar outcomes, robust apostrophe handling avoiding SyntaxError conditions, and sanitized exception detail capturing unexpected failures correctly.
