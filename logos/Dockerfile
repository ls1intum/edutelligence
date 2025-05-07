FROM python:3.13-slim

WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip

COPY pyproject.toml poetry.lock* ./

RUN pip install poetry && \
    poetry self update && \
    poetry env activate && \
    poetry install

COPY ./src ./src
COPY ./tests ./tests
COPY ./db ./db

EXPOSE 8000

CMD ["poetry", "run", "uvicorn", "logos.main:app"]