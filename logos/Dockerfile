FROM python:3.13-slim

WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip

COPY ./logos/pyproject.toml ./logos/poetry.lock* ./

COPY ./logos/src/ ./src/
COPY ./logos/tests/ ./logos/tests/
COPY ./logos/db/ ./logos/db/
COPY ./logos/logos.conf ./logos/logos.conf
COPY ../shared/ ./shared/
COPY ./logos/README.md ./logos/README.md
COPY ./logos/docker-compose.yaml ./logos/docker-compose.yaml

RUN pip install poetry && \
    poetry self update && \
    poetry env activate
RUN poetry install
RUN poetry run python -m grpc_tools.protoc \
  -I . \
  --python_out=. \
  --grpc_python_out=. \
  src/grpclocal/model.proto


EXPOSE 8080

CMD ["poetry", "run", "uvicorn", "logos.main:app", "--host", "0.0.0.0", "--port", "8080"]