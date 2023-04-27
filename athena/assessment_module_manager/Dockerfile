# syntax=docker/dockerfile:1

# This is the Dockerfile for the assessment module manager.

FROM python:3.11

RUN mkdir -p /code/assessment_module_manage
WORKDIR /code/assessment_module_manager

# Poetry
RUN pip install --no-cache-dir poetry==1.4.2

# Dependencies
COPY ./assessment_module_manager/pyproject.toml ./pyproject.toml
COPY ./assessment_module_manager/poetry.lock ./poetry.lock
# athena module (also a dependency)
COPY ./athena /code/athena
# install all dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Project files
COPY ./assessment_module_manager .

# Use modules configuration file for docker
RUN mv ./modules.docker.ini ./modules.ini

CMD poetry run assessment_module_manager