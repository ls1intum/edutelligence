# syntax=docker/dockerfile:1

# This is the general Dockerfile for the assessment module manager.

FROM python:3.11

WORKDIR /code

# Dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# modules configuration file
COPY ./modules.docker.ini /code/modules.ini

# athena module
COPY ./athena /code/athena

# assessment module manager
COPY ./assessment_module_manager /code/assessment_module_manager

CMD python -m assessment_module_manager