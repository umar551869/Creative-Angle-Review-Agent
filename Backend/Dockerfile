# syntax=docker/dockerfile:1
#
# Creative Audit API
#
# Two stages, and the split is not cosmetic: the wheel build needs compilers,
# the runtime does not, and shipping them costs ~400 MB and a larger attack
# surface for no benefit.
#
#   docker build -t audit-api .
#   docker run --rm -p 8000:8000 --env-file .env -v audit-data:/data audit-api
#
# SIZE NOTE. This image is ~2.5 GB, nearly all of it torch + the model weights
# baked in at build time. That is deliberate: downloading ~1.8 GB from Hugging
# Face on every cold start would dominate the runtime of a scale-to-zero
# deployment. Pass --build-arg BAKE_MODELS=false to trade image size for cold
# start instead.

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

# TORCH, ARCH-AWARE.
#
# x86_64: the default PyPI wheel drags in ~2 GB of CUDA libraries this pipeline
# never uses -- vision is hosted, Whisper runs CPU int8, BGE runs on CPU -- so
# the CPU index is worth asking for. Installing it FIRST also stops the
# requirements resolver pulling the CUDA build back in.
#
# aarch64 (Oracle Ampere A1, AWS Graviton): there is no CUDA build to avoid --
# PyPI's manylinux aarch64 wheel is already CPU-only -- and the /whl/cpu index
# does not reliably carry one, so asking for it turns a working build into a
# resolver error. Verified: torch, ctranslate2, onnxruntime, av, opencv,
# scipy, tokenizers and the rest all publish manylinux_*_aarch64 wheels, so
# ARM installs from wheels with no compiler.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && if [ "$(uname -m)" = "x86_64" ]; then \
         /opt/venv/bin/pip install torch \
           --index-url https://download.pytorch.org/whl/cpu; \
       else \
         echo "aarch64: PyPI torch is already CPU-only" \
         && /opt/venv/bin/pip install torch; \
       fi \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# ffmpeg is NOT pip-installable and is the first thing a job touches. Without
# it the container starts, /health says ok, and every job dies in Phase 1.
# UID 1000, not 10001. Hugging Face Spaces runs the container as uid 1000 and
# does not consult USER -- a mismatch means every write to /data and /models
# fails with EACCES, which surfaces as a job dying in Phase 1 rather than as a
# permissions error. 1000 is also the conventional first user elsewhere, so
# this costs nothing on a VPS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 audit

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AUDITOR_DATA_ROOT=/data \
    HF_HOME=/models \
    AUDITOR_LOG_JSON=true

WORKDIR /app
COPY --chown=audit:audit auditor/ ./auditor/
COPY --chown=audit:audit app/ ./app/
COPY --chown=audit:audit tools/ ./tools/
COPY --chown=audit:audit requirements.txt ./

# World-writable, not just audit-writable. A platform that overrides the user
# (Spaces, some PaaS) otherwise lands on a directory it cannot write, and the
# failure appears in Phase 1 as a decode error rather than as EACCES.
RUN mkdir -p /data /models \
    && chown -R audit:audit /data /models /app \
    && chmod -R 777 /data /models
USER audit

# Bake the weights in. ~1.8 GB fetched once at BUILD time instead of on every
# cold start. Failure is not fatal -- the runtime downloads on first use --
# because a Hub outage must not break an image build.
#
# A SCRIPT, not an inline `python -c` with line continuations. That form is
# unreviewable, unrunnable outside the build, and one stray backslash from
# silently baking nothing. tools/bake_models.py can be run locally and says
# what it cached.
ARG BAKE_MODELS=true
RUN if [ "$BAKE_MODELS" = "true" ]; then python tools/bake_models.py; fi

EXPOSE 8000

# Liveness only. Readiness is /ready, which reports the model probe and any
# missing configuration -- pointing a restart policy at that would loop a
# container forever over a missing API key.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# ONE WORKER. The job store and the pipeline namespace live in this process;
# --workers N gives N independent stores and N model loads. Scale by adding
# containers with a shared AUDITOR_DATA_ROOT -- the artifact store is
# content-addressed, so that is safe.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-graceful-shutdown", "25"]
