FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install system packages needed for building wheels and compiling protos
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Install Poetry (will be used to install dependencies). Keep separate layer for caching.
RUN pip install --no-cache-dir "poetry>=1.8"

# Copy only dependency manifests first to maximise layer caching. This Dockerfile
# expects you to build from the repository root with the build context set to the
# repo root, e.g. `docker build -f logos/Dockerfile .`
COPY logos/pyproject.toml logos/poetry.lock* ./
COPY shared/ ./shared/

# Install project dependencies into the container Python environment (no venvs)
RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi --no-root

# Copy source after dependencies to preserve Docker cache for deps
COPY logos/src/ ./src/

# Generate gRPC python code from proto(s)
RUN if [ -f src/grpclocal/model.proto ]; then \
      python -m grpc_tools.protoc -I src --python_out=src --grpc_python_out=src src/grpclocal/model.proto; \
    fi

# Copy other project files
COPY logos/db/ ./logos/db/
COPY logos/tests/ ./tests/

EXPOSE 8080 50051

# Run uvicorn directly; dependencies are installed into the system site-packages
CMD ["uvicorn", "logos.main:app", "--host", "0.0.0.0", "--port", "8080"]
