# img2text server image (Plan G Task 1; ruling R39: pandoc in image).
FROM python:3.11-slim

# R39: pandoc static tarball (jgm/pandoc release asset linux-amd64), same no-sudo approach as host R25.
ARG PANDOC_VERSION=3.10.2
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl poppler-utils libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 \
        fontconfig fonts-dejavu-core fonts-dejavu-extra \
    && curl -fsSL -o /tmp/pandoc.tar.gz \
        "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/pandoc.tar.gz -C /tmp \
    && mv "/tmp/pandoc-${PANDOC_VERSION}/bin/pandoc" /usr/local/bin/pandoc \
    && rm -rf "/tmp/pandoc-${PANDOC_VERSION}" /tmp/pandoc.tar.gz /var/lib/apt/lists/* \
    && pandoc --version

WORKDIR /app

COPY server/ /app/server/
# REFERENCE_DOCX in convert.py resolves <repo-root>/deploy/reference.docx.
COPY deploy/reference.docx /app/deploy/reference.docx

# Plan K2: [kaggle] extra installs the Kaggle API client — the server imports
# it lazily and orchestration self-disables without it (no hard dependency).
RUN pip install --no-cache-dir "/app/server[kaggle]"

# convert.py default PANDOC_BIN points at gitignored server/.tools; image uses /usr/local/bin.
ENV PANDOC_BIN=/usr/local/bin/pandoc
# Source-tree app/ wins over site-packages so REFERENCE_DOCX resolves to /app/deploy/.
ENV PYTHONPATH=/app/server

# Non-root: uvicorn runs as appuser; LOG_PATH default writes /app/logs.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/logs \
    && chown -R appuser:appuser /app
USER appuser

# Single worker by design — in-process rate limits assume it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
