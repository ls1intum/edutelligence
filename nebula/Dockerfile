FROM python:3.13-alpine

RUN apk update && \
    apk add --no-cache gcc musl-dev postgresql-dev rust cargo curl

RUN pip install poetry==2.1.1

WORKDIR /app

# Create the proper directory structure
RUN mkdir -p /app/nebula /app/shared

# Copy shared library into the right location
COPY shared/ /app/shared/

# Copy nebula files
COPY nebula/pyproject.toml nebula/poetry.lock /app/nebula/
COPY nebula/src/ /app/nebula/src/

# Set working directory to hyperion folder where the poetry config is
WORKDIR /app/nebula/

# Install dependencies but don't try to install the current project
RUN poetry install --no-root

# Expose the gRPC port
EXPOSE 50051

# Use our custom entrypoint script
ENTRYPOINT ["poetry", "run", "nebula"]