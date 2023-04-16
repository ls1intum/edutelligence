# syntax=docker/dockerfile:1

# This is the general Dockerfile applied to the modules.
# Input: MODULE_NAME (the folder name, e.g. "module_example")

FROM python:3.11

WORKDIR /code

# Dependencies
COPY ./${MODULE_NAME}/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# athena module
COPY ./athena /code/athena

COPY ./${MODULE_NAME} /code/${MODULE_NAME}

CMD python -m ${MODULE_NAME}