FROM python:3.12-slim

WORKDIR /app

# Install Poetry and dependencies
COPY nebula/pyproject.toml nebula/poetry.lock ./
RUN pip install poetry && poetry install --only main --no-root

# Copy source code and config
COPY nebula/src/nebula ./nebula

# Set PYTHONPATH for relative imports
ENV PYTHONPATH=/app

# Expose FastAPI port
EXPOSE 3871

# Start FastAPI app via uvicorn
CMD ["poetry", "run", "uvicorn", "nebula.faq.app:app", "--host", "0.0.0.0", "--port", "3871"]
