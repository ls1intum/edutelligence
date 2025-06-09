# Dockerfile to build a container image for a Python 3.12 FastAPI application
FROM python:3.12.3-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY pyproject.toml poetry.lock ./

# Install poetry
RUN pip install poetry

# Install any dependencies
RUN poetry install --only main --no-root

# Copy the content of the local src directory to the working directory
COPY src/iris ./iris

# Specify the command to run on container start
CMD ["poetry", "run", "uvicorn", "iris.main:app", "--host", "0.0.0.0", "--port", "8000"]
