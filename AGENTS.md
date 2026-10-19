# Agent Guidelines for DubTitlerr

## Project Architecture
- Single Dockerized pipeline (`ghcr.io/xenarathon/dubtitlerr`).
- Core stages: Audio extraction -> Faster-Whisper transcription -> Proper noun glossary correction -> LLM repair (OpenAI endpoint) -> Subtitle/Sign/Song merge -> MKV mux.
- Web UI on port 8842 with review queue and Runs page.

## Testing & Verification
- Unit test framework: `pytest`
- To run tests: `pytest tests/`
- Every fix or feature must include a passing unit test in `tests/`.
- Ensure idempotency: media files must never be corrupted if a process crashes mid-mux.

## Conventions
- Conventional Commits: Use `fix:`, `feat:`, `chore:`, or `test:`.
- Subtitle styling: Maintain `.ass` override tags (`\pos`, `\an`, `\fad`) and keep sign/song events anchored properly.
- Cloud Endpoints: Ensure all LLM calls conform to OpenAI REST API specs so hosted Gemini 3.x Flash and local engines (Ollama/llama.cpp) remain drop-in compatible.