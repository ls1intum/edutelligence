# Multi-stage build for production
FROM python:3.13-alpine AS builder

# Install build dependencies
RUN apk update && \
    apk add --no-cache \
    gcc \
    musl-dev \
    postgresql-dev \
    rust \
    cargo

# Install Poetry
RUN pip install poetry==2.1.1

# Configure Poetry for production
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VENV_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/opt/poetry_cache

# Set up build directory
WORKDIR /app

# Create the proper directory structure
RUN mkdir -p /app/hyperion /app/shared

# Copy shared library
COPY shared/ /app/shared/

# Copy hyperion files
COPY hyperion/pyproject.toml hyperion/poetry.lock /app/hyperion/

# Set working directory to hyperion folder where the poetry config is
WORKDIR /app/hyperion

# Install dependencies (no dev dependencies for production)
RUN poetry install --only=main --no-root && rm -rf $POETRY_CACHE_DIR

# Production stage
FROM python:3.13-alpine AS production

# Install runtime dependencies only
RUN apk update && \
    apk add --no-cache \
    postgresql-dev \
    curl

# Create non-root user for security
RUN addgroup -g 1001 -S hyperion && \
    adduser -S hyperion -u 1001 -G hyperion

# Copy virtual environment from builder stage
COPY --from=builder /app/hyperion/.venv /app/hyperion/.venv

# Copy shared library
COPY --from=builder /app/shared /app/shared

# Copy application code
COPY hyperion/app/ /app/hyperion/app/

# Set up environment
ENV PATH="/app/hyperion/.venv/bin:$PATH" \
    PYTHONPATH=/app/hyperion:/app \
    PYTHONUNBUFFERED=1

# Change to non-root user
USER hyperion

# Set working directory
WORKDIR /app/hyperion

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Expose port
EXPOSE 8000

# Run the app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]