# docker/gateway/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install Poetry + dependencies
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --only main --no-root

# Copy source code (außer protos und stubs)
COPY src/nebula ./nebula
COPY application_local.nebula.yml ./

# Copy proto definitions
COPY src/nebula/protos ./nebula/protos

# Compile proto to grpc_stubs. This should be done in the compose later on
RUN poetry run python -m grpc_tools.protoc \
    -I=nebula/protos \
    --python_out=nebula/grpc_stubs \
    --grpc_python_out=nebula/grpc_stubs \
    nebula/protos/faq.proto && \
    echo "✅ Proto compiled!" && \
    ls -l nebula/grpc_stubs


RUN sed -i 's/^import faq_pb2/import nebula.grpc_stubs.faq_pb2/' nebula/grpc_stubs/faq_pb2_grpc.py


# Set Python path so modules are discoverable
ENV PYTHONPATH=/app

# Start FastAPI (oder später kombiniert mit gRPC)
CMD ["poetry", "run", "uvicorn", "nebula.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
