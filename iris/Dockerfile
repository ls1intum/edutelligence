# syntax=docker/dockerfile:1

# Dockerfile to build a container image for the Iris FastAPI application

# Stage 1: Builder — install dependencies in a virtual environment using uv
FROM python:3.12.3-slim AS builder

WORKDIR /app

# Install uv (10-100x faster than pip/poetry for dependency resolution)
COPY --from=ghcr.io/astral-sh/uv:0.10.3 /uv /usr/local/bin/uv

# Create virtual environment
RUN uv venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:$PATH"

# Copy dependency metadata first (for layer caching)
COPY iris/pyproject.toml iris/poetry.lock ./

# Copy memiris (path dependency required for resolution)
COPY memiris ../memiris

# Create a stub package so uv can resolve the project without full source
RUN mkdir -p src/iris && echo '__version__ = "3.0.0"' > src/iris/__init__.py && touch README.MD

# Install all main dependencies (cached unless pyproject.toml or memiris changes)
RUN --mount=type=cache,target=/root/.cache/uv uv pip install .

# Stage 2: Runtime — slim image without build tools
FROM python:3.12.3-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy only the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:$PATH"

# Copy the content of the local src directory to the working directory
COPY iris/src/iris ./iris

# Copy logging configuration
COPY iris/log_conf.yml ./log_conf.yml

# Specify the command to run on container start
# Note: Logging is configured programmatically in iris.main via setup_logging()
CMD ["uvicorn", "iris.main:app", "--host", "0.0.0.0", "--port", "8000"]
