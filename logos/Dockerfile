# ──────────────────────────────────────────────────────────
# Stage 1: Builder – compile wheels and install dependencies
# ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install system packages needed for compiling C-extension wheels
RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install uv – a drop-in pip replacement written in Rust (10-100× faster)
# Pinned to a specific version to mitigate supply-chain risk (update explicitly)
COPY --from=ghcr.io/astral-sh/uv:0.10.3 /uv /usr/local/bin/uv

# Create an isolated virtual-env that we will copy into the runtime image
RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── Dependency layer (cached unless pyproject.toml or shared/ changes) ──
COPY logos/pyproject.toml ./
COPY shared/ ./shared/

# Create a minimal package stub so the poetry-core build backend can
# resolve metadata without needing the real source tree.
RUN mkdir -p src/logos && echo '__version__ = "0.1.0"' > src/logos/__init__.py \
 && touch README.md

# Install all dependencies with uv (replaces poetry install ~436 s → ~30-60 s)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install .

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
COPY logos/src/ ./src/

# Generate gRPC python code from proto(s)
RUN if [ -f src/grpclocal/model.proto ]; then \
      python -m grpc_tools.protoc -I src --python_out=src --grpc_python_out=src src/grpclocal/model.proto; \
    fi

# Copy other project files
COPY logos/db/ ./logos/db/
COPY logos/tests/ ./tests/

EXPOSE 8080 50051

CMD ["uvicorn", "logos.main:app", "--host", "0.0.0.0", "--port", "8080"]
