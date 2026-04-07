# syntax=docker/dockerfile:1

# This is the Dockerfile for the module_text_cofee.

# Protobuf build
FROM golang:alpine AS cofee_protobuf
RUN apk update && apk add --no-cache make protobuf-dev
WORKDIR /proto
COPY cofee.proto .
RUN protoc --python_out . cofee.proto


FROM python:3.11
LABEL org.opencontainers.image.source=https://github.com/ls1intum/Athena

# Environment variable Python in Docker
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Copy proto file
COPY --from=cofee_protobuf /proto/cofee_pb2.py ./module_text_cofee/protobuf/

# Poetry
RUN pip install --no-cache-dir poetry==1.5.0

# Dependencies
COPY pyproject.toml poetry.lock ./
# athena module (from the Dockerfile in the athena folder)
COPY --from=athena /code /athena
# install dependencies
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi

# Project files
COPY . ./

# poetry scripts don't work here
CMD poetry run python -m module_*
