FROM python:3.13-slim

WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip

RUN pip install poetry && \
    poetry self update && \
    poetry env activate

COPY ../shared/ ./shared/
COPY ./logos/pyproject.toml ./logos/poetry.lock* ./

RUN poetry install
RUN poetry run python -m grpc_tools.protoc \
  -I . \
  --python_out=. \
  --grpc_python_out=. \
  src/grpclocal/model.proto

COPY ./logos/db/ ./logos/db/
COPY ./logos/tests/ ./tests/
COPY ./logos/src/ ./src/

EXPOSE 8080
EXPOSE 50051

CMD ["poetry", "run", "uvicorn", "logos.main:app", "--host", "0.0.0.0", "--port", "8080"]
