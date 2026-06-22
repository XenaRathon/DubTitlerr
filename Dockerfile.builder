# dubtitle-builder — the WHOLE pipeline (GPU transcribe + LLM repair + signs/songs merge +
# Plex refresh) as one long-running, restart-safe service. Built FROM subgen for the exact
# CUDA / faster-whisper / ctranslate2 stack already proven on the 1060 (Pascal) + driver 550.
# DockHand can't build images -> build on the host and reference fasc/dubtitle-builder:latest.
FROM mccloud/subgen:2026.06.2

# subgen ships python3 + ffmpeg but no pip; bootstrap pip to add pysubs2 (for the merge step).
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && python3 -m pip install --no-cache-dir pysubs2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY generate.py repair.py dub_signs_merge.py plex_refresh.py \
     merge_pass.sh gen_loop.sh container_run.sh /app/
RUN chmod +x /app/*.sh

# Bypass subgen's init (we only want its runtime); run our two-loop supervisor as root so
# generate.py can chown sidecars to MEDIA_UID:MEDIA_GID.
ENTRYPOINT ["sh", "/app/container_run.sh"]
