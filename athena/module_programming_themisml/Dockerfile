# syntax=docker/dockerfile:1

# This is the Dockerfile for the module_example.

# Pytorch CPU version is not yet available for Python 3.12
FROM python:3.11-alpine
LABEL org.opencontainers.image.source=https://github.com/pal03377/Athena-New
 
# Environment variable Python in Docker
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Build tools for poetry
RUN apk add --no-cache gcc g++ libffi-dev

# Poetry
RUN pip install --no-cache-dir poetry==1.3.0 # needs to be 1.3.0 because of https://github.com/python-poetry/poetry/issues/7611

# Dependencies
COPY pyproject.toml poetry.lock ./
# athena module (from the Dockerfile in the athena folder)
COPY --from=athena /code /athena
# install dependencies
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-interaction --no-ansi

# Re-install pytorch in the CPU version because we don't have a GPU
RUN poetry add https://download.pytorch.org/whl/cpu/torch-2.1.0%2Bcpu-cp311-cp311-linux_x86_64.whl
# Somehow, the torch library needs sympy to be installed manually as well
RUN poetry add sympy==1.12

# Project files
COPY . ./

# poetry scripts don't work here
CMD poetry run python -m module_*