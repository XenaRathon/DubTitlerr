# dubtitle-builder — the WHOLE pipeline (GPU transcribe + LLM repair + signs/songs merge +
# Plex refresh) as one long-running, restart-safe service. Built FROM subgen for the exact
# CUDA / faster-whisper / ctranslate2 stack already proven on the 1060 (Pascal) + driver 550.
# DockHand can't build images -> build on the host and reference fasc/dubtitle-builder:latest.
FROM mccloud/subgen:2026.06.2

# subgen ships python3 + ffmpeg but no pip; bootstrap pip to add pysubs2 (for the merge step).
# wamerican = /usr/share/dict/american-english, the English-word gate for glossary.py (C1).
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip wamerican \
    && python3 -m pip install --no-cache-dir pysubs2 \
    && rm -rf /var/lib/apt/lists/*

# Bake the Whisper large-v3 model into the image (~3GB) so the container is fully
# self-contained — no dependency on an external models bind-mount. Fetched once at build
# time (CPU, just to download the files). MODEL_DIR points generate.py at it.
ENV MODEL_DIR=/models
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8', download_root='/models')"

WORKDIR /app
COPY generate.py reflow.py glossary.py hallucination.py common_words.txt repair.py \
     dub_signs_merge.py plex_refresh.py mine_glossary.py merge_pass.sh gen_loop.sh \
     container_run.sh /app/
RUN chmod +x /app/*.sh

# Bypass subgen's init (we only want its runtime); run our two-loop supervisor as root so
# generate.py can chown sidecars to MEDIA_UID:MEDIA_GID.
ENTRYPOINT ["sh", "/app/container_run.sh"]
