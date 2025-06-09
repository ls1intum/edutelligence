# Dockerfile to build a container image for a Python 3.12 gRPC application
FROM python:3.12.3-slim

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install poetry and dependencies
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --with dev --no-root

# Copy source code
COPY src ./src

# Compile .proto file
RUN python -m grpc_tools.protoc \
    -I src/nebula/services/faq_service \
    --python_out=src \
    --grpc_python_out=src \
    src/nebula/services/faq_service/faq.proto

# Expose gRPC port
EXPOSE 50051

# Add src to PYTHONPATH so "nebula" is recognized
ENV PYTHONPATH=/app/src

# Run gRPC server
CMD ["python", "-m", "nebula.main"]
