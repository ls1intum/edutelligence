# syntax=docker/dockerfile:1

# Stage 1: Builder — install dependencies in a virtual environment
FROM python:3.12-slim AS builder

WORKDIR /app

# Copy dependency files first
COPY nebula/pyproject.toml nebula/poetry.lock ./

# Install poetry and dependencies into an in-project venv
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --only main --no-root \
    && pip uninstall -y poetry

# Stage 2: Runtime — slim image with only runtime system dependencies
FROM python:3.12-slim

# Runtime system dependencies (ffmpeg, tesseract, OpenCV libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy only the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code and config files
COPY nebula/src/nebula ./nebula

# Set PYTHONPATH so Python can find src/nebula
ENV PYTHONPATH=/app

# Expose FastAPI port
EXPOSE 3870

# Run app
CMD ["uvicorn", "nebula.transcript.app:app", "--host", "0.0.0.0", "--port", "3870"]
