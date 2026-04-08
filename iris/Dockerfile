# Dockerfile to build a container image for a Python 3.12 FastAPI application
FROM python:3.12.3-slim

# Install system dependencies for video transcription
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY iris/pyproject.toml iris/poetry.lock ./

COPY memiris ../memiris

# Install poetry
RUN pip install poetry

# Install any dependencies
RUN poetry install --only main --no-root

# Copy the content of the local src directory to the working directory
COPY iris/src/iris ./iris

# Copy logging configuration
COPY iris/log_conf.yml ./log_conf.yml

# Specify the command to run on container start
# Note: Logging is configured programmatically in iris.main via setup_logging()
CMD ["poetry", "run", "uvicorn", "iris.main:app", "--host", "0.0.0.0", "--port", "8000"]
