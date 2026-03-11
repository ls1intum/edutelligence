# syntax=docker/dockerfile:1

# This is the Dockerfile for the assessment module manager.

# Stage 1: Builder — install dependencies in a virtual environment
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Poetry
RUN pip install --no-cache-dir poetry==1.5.0

# Dependencies
COPY pyproject.toml poetry.lock ./
# athena module (from the Dockerfile in the athena folder)
COPY --from=athena /code /athena
# install dependencies into an in-project venv
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi

# Stage 2: Runtime — slim image without compilers or dev tools
FROM python:3.11-slim
LABEL org.opencontainers.image.source=https://github.com/ls1intum/Athena

ENV PYTHONUNBUFFERED=1

# Runtime dependency for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Copy only the virtual environment from the builder
COPY --from=builder /code/.venv /code/.venv
ENV PATH="/code/.venv/bin:$PATH"

# Project files
COPY . ./

# Use modules configuration file for docker
RUN mv ./modules.docker.ini ./modules.ini

CMD ["python", "-m", "assessment_module_manager"]
