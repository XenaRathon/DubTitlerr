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

# Bake the Whisper large-v3-turbo model into the image (~1.5GB) so the container is fully
# self-contained — no dependency on an external models bind-mount. Fetched once at build
# time (CPU, just to download the files). MODEL_DIR points generate.py at it.
ENV MODEL_DIR=/models
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8', download_root='/models')"

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
COPY generate.py reflow.py glossary.py glossary_verify.py hallucination.py ordering.py common.py common_words.txt \
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
