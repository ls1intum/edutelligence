# syntax=docker/dockerfile:1

# Stage 1: Builder — install dependencies in a virtual environment
FROM python:3.12-slim AS builder

WORKDIR /app

# Install Poetry and dependencies
COPY nebula/pyproject.toml nebula/poetry.lock ./
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --only main --no-root \
    && pip uninstall -y poetry

# Stage 2: Runtime — slim image without build tools
FROM python:3.12-slim

WORKDIR /app

# Copy only the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code and config
COPY nebula/src/nebula ./nebula

# Set PYTHONPATH for relative imports
ENV PYTHONPATH=/app

# Expose FastAPI port
EXPOSE 3871

# Start FastAPI app via uvicorn
CMD ["uvicorn", "nebula.faq.app:app", "--host", "0.0.0.0", "--port", "3871"]
