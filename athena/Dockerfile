# syntax=docker/dockerfile:1

FROM python:3.11

ARG MODULE_NAME
ENV MODULE_NAME=${MODULE_NAME}
WORKDIR /code

# Dependencies
COPY ./${MODULE_NAME}/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# athena module
COPY ./athena /code/athena

COPY ./${MODULE_NAME} /code/${MODULE_NAME}

CMD python -m ${MODULE_NAME}