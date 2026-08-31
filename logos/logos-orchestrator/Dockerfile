# ──────────────────────────────────────────────────────────
# Stage 1: Builder – compile wheels and install dependencies
# ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install system packages needed for compiling C-extension wheels
RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc build-essential rustc cargo \
  && rm -rf /var/lib/apt/lists/*

# Install uv – a drop-in pip replacement written in Rust (10-100× faster)
# Pinned to a specific version to mitigate supply-chain risk (update explicitly)
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

# Create an isolated virtual-env that we will copy into the runtime image
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── Dependency layer (cached unless pyproject.toml or the shared package changes) ──
# Copy ONLY the files `uv pip install .` reads to build the `shared` path
# dependency: its metadata (pyproject.toml), its declared readme (required
# by the poetry-core build backend) and the package source itself. The rest
# of shared/ (its own poetry.lock, .flake8, ...) is NOT an input to this
# install — copying it would invalidate this layer (and re-run the whole
# dependency install) on every unrelated shared/ change.
COPY logos/logos-orchestrator/pyproject.toml ./
COPY shared/pyproject.toml ./shared/pyproject.toml
COPY shared/README.md ./shared/README.md
COPY shared/shared/ ./shared/shared/

# Create a minimal package stub so the poetry-core build backend can
# resolve metadata without needing the real source tree.
RUN mkdir -p src/logos && echo '__version__ = "0.1.0"' > src/logos/__init__.py \
 && touch README.md

# Install all dependencies with uv (replaces poetry install ~436 s → ~30-60 s)
# sentence-transformers pulls in torch as a transitive dep; this container has
# no GPU (see docker-compose.yaml — no device reservation for this service),
# so pull the CPU-only build instead of PyPI's default CUDA wheels (which drag
# in ~15 nvidia-cu12 packages and blow the install up from ~1 min to ~8 min).
# torch is pinned to PyTorch's CPU-only wheel index via tool.uv.sources + an
# explicit index in pyproject.toml, so no extra install-time flags are needed
# here to steer it away from PyPI's default CUDA build.
#
# --refresh-package shared: rebuild the local `shared` path dependency from
# current source. Without it, uv's build cache can serve a STALE wheel for
# that dependency: the cache entry is keyed by path+version, not content, so
# after a shared/ source change the (re-run) install layer would silently
# install the previously built code. Reproduced with uv 0.11.3 and 0.12.5.
# The narrow flag invalidates exactly that one build-cache entry — index
# resolution and the cached registry wheels stay untouched, so two builds
# of the same commit keep resolving to the same dependency versions.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --refresh-package shared .

# ──────────────────────────────────────────────────────────
# Stage 2: Runtime – slim image without compilers or build tools
# ──────────────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only install runtime system dependencies (curl for health-checks)
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtual-env from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy source code
COPY logos/logos-orchestrator/src/ ./src/

# Generate gRPC python code from proto(s)
RUN if [ -f src/grpclocal/model.proto ]; then \
      python -m grpc_tools.protoc -I src --python_out=src --grpc_python_out=src src/grpclocal/model.proto; \
    fi

# Copy other project files
COPY logos/db/ ./logos/db/
COPY logos/logos-orchestrator/tests/ ./tests/

EXPOSE 8080 50051

CMD ["uvicorn", "logos.main:app", "--host", "0.0.0.0", "--port", "8080", "--ws-ping-interval", "60", "--ws-ping-timeout", "60", "--ws-max-size", "268435456"]
