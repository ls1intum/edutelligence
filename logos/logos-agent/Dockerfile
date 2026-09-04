# ──────────────────────────────────────────────────────────
# Stage 1: Builder – resolve dependencies into a virtual env
# ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc build-essential \
  && rm -rf /var/lib/apt/lists/*

# Pinned like the orchestrator's build, so a uv release cannot change what
# lands in the image without an explicit bump here.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY logos/logos-agent/pyproject.toml ./
# Package stub so the build backend can read metadata without the source tree,
# keeping this layer cached across code-only changes.
RUN mkdir -p app && echo '__version__ = "0.1.0"' > app/__init__.py && touch README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install .

# ──────────────────────────────────────────────────────────
# Stage 2: Runtime
# ──────────────────────────────────────────────────────────
FROM python:3.13-slim

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY logos/logos-agent/app ./app

# The service needs the Docker socket to create session containers, which is a
# privileged capability: it runs as root inside its own container for that
# reason, and holds no other elevated access. The session containers it
# creates get neither the socket nor root — see app/docker_engine.py.
EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
