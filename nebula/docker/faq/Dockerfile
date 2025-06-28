FROM python:3.12-slim

WORKDIR /app

# Install Poetry and project dependencies
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --only main --no-root

# Copy source code and config
COPY src/nebula ./nebula
COPY application_local.nebula.yml .
COPY llm_config.nebula.yml .

# COMPILE PROTO FROM ROOT CONTEXT!
# This makes relative imports (from . import faq_pb2) work inside grpc_stubs
WORKDIR /app

# Compile .proto file into grpc_stubs
# Compile the proto file
RUN poetry run python -m grpc_tools.protoc \
    -I=nebula/protos \
    --python_out=nebula/grpc_stubs \
    --grpc_python_out=nebula/grpc_stubs \
    nebula/protos/faq.proto && \
    echo "✅ Proto compiled!" && \
    ls -l nebula/grpc_stubs

RUN sed -i 's/^import faq_pb2/import nebula.grpc_stubs.faq_pb2/' nebula/grpc_stubs/faq_pb2_grpc.py


# Debug output: list grpc_stubs content
RUN echo "Contents of grpc_stubs:" && ls -l nebula/grpc_stubs

# Ensure grpc_stubs is a proper Python package
RUN touch nebula/grpc_stubs/__init__.py

# Set PYTHONPATH so packages can be resolved
ENV PYTHONPATH=/app

# Expose the gRPC port
EXPOSE 50052

# Start the FAQ gRPC server
CMD ["poetry", "run", "python", "nebula/faq/faq_server.py"]
