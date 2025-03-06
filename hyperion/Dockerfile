FROM python:3.13-alpine

RUN apk update && \
    apk add --no-cache gcc musl-dev postgresql-dev rust cargo curl

RUN pip install poetry==2.1.1

WORKDIR /app
COPY hyperion/pyproject.toml hyperion/poetry.lock ./

RUN echo "$(ls .. -la)"

COPY ./shared/ .

RUN poetry install --no-root

COPY hyperion/app/ .

CMD ["poetry", "run",  "fastapi", "run", "app/main.py", "--port", "8000"]
