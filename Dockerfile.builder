# dubtitle-builder — the WHOLE pipeline (GPU transcribe + LLM repair + signs/songs merge +
# Plex refresh) as one long-running, restart-safe service. Built FROM subgen for the exact
# CUDA / faster-whisper / ctranslate2 stack already proven on the 1060 (Pascal) + driver 550.
# DockHand can't build images -> build on the host and reference fasc/dubtitle-builder:latest.
FROM mccloud/subgen:2026.06.2

# subgen ships python3 + ffmpeg but no pip; bootstrap pip to add pysubs2 (for the merge step)
# and jellyfish (Metaphone, glossary.py tier-4 phonetic match -- V2 A4/A5).
# wamerican = /usr/share/dict/american-english, the English-word gate for glossary.py (C1).
# mkvtoolnix = mkvmerge for the D1 mux stage (embed .ass + fonts as a default Dubtitles track).
# webrtcvad (Timing Compare U3/T8): tools/vad.py's --vad webrtcvad backend. tools/ itself
# isn't COPY'd into this image (offline analytics, run standalone -- matches
# tools/bakeoff.py, also not baked in); installed here anyway so the dep is available if
# the tool is ever run inside this image/venv. This image's Debian python3 has a prebuilt
# wheel for it (unlike the repo's py3.14 dev venv -- see tools/vad.py's module docstring);
# if that ever regresses, drop this line and use `--vad ffmpeg-silencedetect` instead
# (dep-free, ffmpeg is already in this image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip wamerican mkvtoolnix \
    && python3 -m pip install --no-cache-dir pysubs2 jellyfish \
    && (python3 -m pip install --no-cache-dir webrtcvad || echo "webrtcvad install failed -- analytics-only, use --vad ffmpeg-silencedetect; NOT fatal for generation") \
    && rm -rf /var/lib/apt/lists/*

# Bake one Whisper model into the image so the container is fully self-contained — no
# dependency on an external models bind-mount. Fetched once at build time (CPU, just to
# download the files). MODEL_DIR points generate.py at it.
#
# WHISPER_MODEL is an ARG *and* an ENV on purpose: the build bakes the model this names,
# and the same value becomes the container's runtime default, so the baked model and the
# model generate.py asks for cannot drift apart. A mismatch is not an error — faster-whisper
# would silently re-download the missing model into /models on every container start.
#
#   large-v3       (default, ~3GB)   -- the 1060 6GB box; fits at the default beam_size=7.
#   large-v3-turbo (~1.5GB)          -- the 3500g node's 1050ti 4GB, where large-v3 OOMs at
#                                       beam 7 and only fits forced down to greedy, which is
#                                       measurably worse than turbo at the full beam.
#                                       Build it with:
#                                         docker build -f Dockerfile.builder \
#                                           --build-arg WHISPER_MODEL=large-v3-turbo \
#                                           -t dubtitle-builder:latest .
ARG WHISPER_MODEL=large-v3
ENV WHISPER_MODEL=${WHISPER_MODEL}
ENV MODEL_DIR=/models
RUN python3 -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8', download_root='/models')"

WORKDIR /app
# NOTE (V2-U3 B7/B9): common.py was missing from this COPY list since V1 introduced it --
# every `from common import ...` (generate.py, mine_glossary.py, mux.py, repair.py,
# dub_signs_merge.py) would ImportError at container start. Added here alongside the new
# data/ (EXTRA_DIRS data file) and shell/ (extras_grep_pattern lib) directories that
# merge_pass.sh now sources from $APP/shell/lib.sh + $APP/data/extras.txt.
# recreate_srt.py added: it rebuilds <stem>.eng.dubtitles.srt from the conf.json when the
# srt has already been consumed (mux removes sidecars on success). That is the ONLY way to
# re-run repair on an already-muxed episode without re-transcribing it -- repair.py returns
# "skip" when the srt is absent -- so a model/prompt change cannot be rolled out to the
# existing library without this in the image.
COPY generate.py reflow.py glossary.py glossary_verify.py glossary_acquire.py hallucination.py ordering.py common.py common_words.txt \
     repair.py dub_signs_merge.py mux.py plex_refresh.py mine_glossary.py recreate_srt.py merge_pass.sh \
     gen_loop.sh container_run.sh /app/
COPY data/ /app/data/
COPY shell/ /app/shell/
# tools/ ships for the same reason recreate_srt.py does: recover_dub_srt.py rebuilds the
# srt from the already-muxed Dubtitles track, which is the only way to regenerate an
# episode whose conf.json is gone without sending it back through Whisper.
COPY tools/ /app/tools/
RUN chmod +x /app/*.sh

# Bypass subgen's init (we only want its runtime); run our two-loop supervisor as root so
# generate.py can chown sidecars to MEDIA_UID:MEDIA_GID.
ENTRYPOINT ["sh", "/app/container_run.sh"]
