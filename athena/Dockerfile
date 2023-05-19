# syntax=docker/dockerfile:1

# This is the general Dockerfile applied to the modules.
# Input: MODULE_NAME (the folder name, e.g. "module_example")

FROM python:3.11
LABEL org.opencontainers.image.source=https://github.com/pal03377/Athena-New

ARG MODULE_NAME
RUN mkdir -p /code${MODULE_NAME}
WORKDIR /code/${MODULE_NAME}

# Environment variables for modules running in Docker
ENV PYTHONUNBUFFERED=1
ENV HOST_NAME_FOR_MODULE_URL=1

# Poetry
RUN pip install --no-cache-dir poetry==1.4.2

# Dependencies
COPY ./${MODULE_NAME}/pyproject.toml /code/${MODULE_NAME}/pyproject.toml
COPY ./${MODULE_NAME}/poetry.lock /code/${MODULE_NAME}/poetry.lock
# athena module (also a dependency)
COPY ./athena /code/athena
# install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

COPY ./${MODULE_NAME} /code/${MODULE_NAME}

CMD poetry run module