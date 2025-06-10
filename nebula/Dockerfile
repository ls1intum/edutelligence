FROM python:3.12.3-slim

WORKDIR /app

# Install system dependencies first
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install project dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction --no-ansi

# Copy source code
COPY src ./src

# Compile proto files
RUN python -m grpc_tools.protoc \
    -I=src \
    --python_out=src \
    --grpc_python_out=src \
    src/nebula/services/faq_service/faq.proto

# Set Python path to include both /app and /app/src
ENV PYTHONPATH="${PYTHONPATH}:/app:/app/src"

# Install langchain-core explicitly (if needed)
RUN pip install langchain-core

CMD ["python", "src/nebula/main.py"]