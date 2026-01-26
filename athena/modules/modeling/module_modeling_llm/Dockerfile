# syntax=docker/dockerfile:1

# This is the Dockerfile for the modeling exercise feedback module.

FROM python:3.11
LABEL org.opencontainers.image.source=https://github.com/ls1intum/Athena

# Environment variable Python in Docker
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Poetry
RUN pip install --no-cache-dir poetry==1.5.0

# Dependencies
COPY pyproject.toml poetry.lock ./
# athena module (from the Dockerfile in the athena folder)
COPY --from=athena /code /athena
COPY --from=llm_core /code /llm_core
# install dependencies
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi

# Project files
COPY . ./

RUN poetry install --no-interaction --no-ansi

# poetry scripts don't work here
CMD poetry run python -m module_*