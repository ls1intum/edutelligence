# syntax=docker/dockerfile:1

FROM python:3.11

WORKDIR /code

# Dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY . /code/module

CMD ["python", "-m", "module"]