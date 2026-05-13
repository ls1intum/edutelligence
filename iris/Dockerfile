# Dockerfile to build a container image for a Python 3.13 FastAPI application
FROM python:3.13.3-slim

# Install system dependencies for video transcription and model download
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY iris/pyproject.toml iris/poetry.lock ./

COPY memiris ../memiris

# Install poetry
RUN pip install "poetry>=2.1,<3"

# Install any dependencies
RUN poetry install --only main --no-root

# Copy the content of the local src directory to the working directory
COPY iris/src/iris ./iris

# Copy logging configuration
COPY iris/log_conf.yml ./log_conf.yml

# Copy intent-classifier model config files (small, not in LFS)
COPY iris/models ./models

# Download the quantized ONNX model from Hugging Face (too large for git, stored externally)
RUN curl -fsSL \
    "https://huggingface.co/NayerKotry/iris-intent-classifier/resolve/main/model_quantized.onnx" \
    -o /app/models/global_search_intent/onnx/model_quantized.onnx

ENV INTENT_MODEL_DIR=/app/models/global_search_intent/onnx

# Specify the command to run on container start
# Note: Logging is configured programmatically in iris.main via setup_logging()
CMD ["poetry", "run", "uvicorn", "iris.main:app", "--host", "0.0.0.0", "--port", "8000"]
