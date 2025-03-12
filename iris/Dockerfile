# Dockerfile to build a container image for a Python 3.12 FastAPI application
FROM python:3.12.3-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY iris/pyproject.toml poetry.lock ./

# Install poetry
RUN pip install poetry

# Install any dependencies
RUN poetry install --only main

# Copy the content of the local src directory to the working directory
COPY iris/src/ ./src

# Specify the command to run on container start
CMD ["uvicorn", "src.iris.main:app", "--host", "0.0.0.0", "--port", "8000"]
