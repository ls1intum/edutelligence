FROM python:3.12-slim

WORKDIR /app

# Install Poetry and dependencies
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --only main --no-root

# Copy source code and config
COPY src/nebula ./nebula

# Set PYTHONPATH for relative imports
ENV PYTHONPATH=/app

# Expose FastAPI port
EXPOSE 5001

# Start FastAPI app via uvicorn
CMD ["poetry", "run", "uvicorn", "nebula.faq.app:app", "--host", "0.0.0.0", "--port", "5001"]