# Use Python 3.12 slim image
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy dependency files first
COPY pyproject.toml poetry.lock ./

# Install poetry
RUN pip install poetry

# Install only main dependencies
RUN poetry install --only main --no-root

# Copy source code and config files
COPY src/nebula ./src/nebula
COPY llm_config.nebula.yml .

# Set PYTHONPATH so Python can find src/nebula
ENV PYTHONPATH=/app/src

# Expose FastAPI port
EXPOSE 5000

# Run app
CMD ["poetry", "run", "uvicorn", "nebula.transcript.app:app", "--host", "0.0.0.0", "--port", "5000"]
