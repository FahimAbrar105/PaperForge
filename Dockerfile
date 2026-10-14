# Paper Forge image: Python backend + static frontend + Tectonic with a pre-filled
# LaTeX package cache, so compiling works without network access at runtime.
FROM python:3.12-slim

ARG TECTONIC_VERSION=0.15.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TECTONIC_CACHE_DIR=/opt/tectonic-cache \
    PAPERFORGE_TECTONIC=/usr/local/bin/tectonic \
    PAPERFORGE_HOST=0.0.0.0 \
    PAPERFORGE_PORT=8000 \
    PAPERFORGE_DATA_DIR=/app/output

# curl + certificates only for the build-time download; fontconfig is required by Tectonic.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libfontconfig1 \
 && ARCH="$(uname -m)" \
 && case "$ARCH" in \
      x86_64)  T="x86_64-unknown-linux-musl" ;; \
      aarch64) T="aarch64-unknown-linux-musl" ;; \
      *) echo "Unsupported architecture $ARCH" && exit 1 ;; \
    esac \
 && curl -L --fail --retry 3 -o /tmp/tectonic.tar.gz \
      "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${T}.tar.gz" \
 && tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin \
 && rm /tmp/tectonic.tar.gz \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
COPY vendor ./vendor
RUN pip install --only-binary :all: --find-links vendor/wheels -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY venue_rules ./venue_rules
COPY sample_paper ./sample_paper
COPY scripts ./scripts

# Compile the sample paper once per venue so every package the templates need is cached in the image.
RUN python scripts/warmup.py && rm -rf /app/output/* /tmp/*

RUN useradd --create-home --uid 1000 paperforge \
 && mkdir -p /app/output && chown -R paperforge /app/output /opt/tectonic-cache
USER paperforge

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "app.main"]
