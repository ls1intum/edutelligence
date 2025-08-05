FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends  \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

# Ensure venv is created in project directory
ENV POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /atlasml

COPY pyproject.toml poetry.lock README.md  ./ 
COPY atlasml/ ./atlasml/

RUN poetry install


FROM python:3.13-slim as runtime

WORKDIR /atlasml

RUN apt-get update && apt-get install -y --no-install-recommends  \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment and source code
COPY --from=builder /atlasml/.venv /atlasml/.venv
COPY --from=builder /atlasml/atlasml /atlasml/atlasml

# Set environment variables to use the virtual environment
ENV VIRTUAL_ENV=/atlasml/.venv
ENV PATH="/atlasml/.venv/bin:$PATH"

# Copy configuration files
COPY application.yml ./

EXPOSE 8000

CMD ["/atlasml/.venv/bin/uvicorn", "atlasml.app:app", "--host", "0.0.0.0", "--port", "8000"]