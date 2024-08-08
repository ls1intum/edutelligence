# syntax=docker/dockerfile:1

# This is the Dockerfile for the module_programming_themisml.

# Pytorch CPU version is not yet available for Python 3.12
FROM python:3.11
LABEL org.opencontainers.image.source=https://github.com/pal03377/Athena-New

# Environment variable Python in Docker
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Poetry
RUN pip install --no-cache-dir poetry==1.6.1

# Dependencies
COPY pyproject.toml poetry.lock ./
# athena module (from the Dockerfile in the athena folder)
COPY --from=athena /code /athena
# install dependencies
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi

# Project files
COPY ../../../athena ./

# poetry scripts don't work here
CMD poetry run python -m module_*