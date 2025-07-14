FROM python:3.13-slim

# Install minimal dependencies and grpc_health_probe
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install grpc_health_probe for proper gRPC health checking
ARG GRPC_HEALTH_PROBE_VERSION=v0.4.25
RUN wget -qO/bin/grpc_health_probe \
      https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64 \
    && chmod +x /bin/grpc_health_probe

# Install poetry
RUN pip install poetry==2.1.1

WORKDIR /app

# Create the directory structure to match pyproject.toml expectations
RUN mkdir -p hyperion

# Copy shared library to parent directory (for path dependency)
COPY shared/ ./shared/

# Copy hyperion files to hyperion subdirectory
COPY hyperion/pyproject.toml ./hyperion/
COPY hyperion/app/ ./hyperion/app/

# Change to hyperion directory for poetry install
WORKDIR /app/hyperion

# Install dependencies (without lock file to avoid path issues)
RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root

# Create non-root user
RUN useradd --create-home --shell /bin/bash hyperion

# Create certificates directory
RUN mkdir -p /certs && chown hyperion:hyperion /certs

# Switch to non-root user
USER hyperion

# Expose the gRPC port
EXPOSE 50051

# Start the application
ENTRYPOINT ["python", "-c", "from app.main import serve; serve()"]