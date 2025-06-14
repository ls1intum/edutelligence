FROM python:3.13-alpine

# Install required system dependencies
RUN apk update && \
    apk add --no-cache gcc musl-dev postgresql-dev rust cargo curl

# Install Poetry package manager
RUN pip install poetry==2.1.1

# Set the working directory inside the container
WORKDIR /app

# Copy only the dependency definitions first to leverage Docker layer caching
COPY pyproject.toml poetry.lock /app/

# Copy the actual application source code
COPY src/ /app/src/

# Set PYTHONPATH so Python can resolve modules starting from /app/src
ENV PYTHONPATH=/app/src

# Install dependencies defined in pyproject.toml, but do not install the project itself
RUN poetry install --no-root

# Generate the gRPC stubs from the .proto files
RUN poetry run generate-grpc

# Expose the gRPC server port
EXPOSE 50051

# Set PYTHONPATH again to ensure it's available at runtime (redundant but safe)
ENV PYTHONPATH="/app/src"

# Run the main application using Poetry
CMD ["poetry", "run", "nebula"]
