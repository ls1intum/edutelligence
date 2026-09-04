# syntax=docker/dockerfile:1

# This is the Dockerfile for the athena package.
# Its output is used as a dependency in the module_* Dockerfiles.

FROM python:3.11 AS athena

WORKDIR /code

# Poetry
ARG POETRY_VERSION=2.4.1
ENV POETRY_HOME=/opt/poetry
ENV PATH="/opt/poetry/bin:${PATH}"
RUN python -m venv "${POETRY_HOME}" \
    && "${POETRY_HOME}/bin/pip" install --no-cache-dir "poetry==${POETRY_VERSION}"

# Dependencies
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --no-ansi

# Project files
COPY . ./

# Build the package
RUN poetry build -f wheel
# The output is in /code/dist
