# docker/gateway/Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --only main --no-root

COPY src/nebula ./nebula
COPY application_local.nebula.yml ./

ENV PYTHONPATH=/app

CMD ["poetry", "run", "uvicorn", "nebula.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
