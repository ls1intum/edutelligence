# Use Python 3.12 slim image
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy dependency files first
COPY nebula/pyproject.toml nebula/poetry.lock ./

# Install poetry
RUN pip install poetry

# Install only main dependencies
RUN poetry install --only main --no-root

# Copy source code
COPY nebula/src/nebula ./nebula

# Create storage directories
RUN mkdir -p /app/video_storage /app/temp

# Set PYTHONPATH so Python can find src/nebula
ENV PYTHONPATH=/app

# Expose FastAPI port
EXPOSE 3872

# Run app
CMD ["poetry", "run", "uvicorn", "nebula.video_storage.app:app", "--host", "0.0.0.0", "--port", "3872"]
