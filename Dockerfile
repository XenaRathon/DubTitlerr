FROM python:3.13-slim

# ffmpeg/ffprobe to read + extract subtitle streams; pysubs2 to merge them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pysubs2

WORKDIR /app
COPY dub_signs_merge.py /app/dub_signs_merge.py

# Mount your media at /data and run:
#   docker run --rm -u 0 -v /path/to/media:/data dub-signs-merge
CMD ["python", "/app/dub_signs_merge.py"]
