FROM python:3.13-alpine

RUN apk update && \
    apk add --no-cache gcc musl-dev postgresql-dev rust cargo curl

RUN pip install poetry==2.1.1

WORKDIR /app

# Create the proper directory structure
RUN mkdir -p /app/hyperion /app/shared

# Copy shared library into the right location
COPY shared/ /app/shared/

# Copy hyperion files
COPY hyperion/pyproject.toml hyperion/poetry.lock /app/hyperion/
COPY hyperion/app/ /app/hyperion/app/

# Set working directory to hyperion folder where the poetry config is
WORKDIR /app/hyperion

# Install dependencies
RUN poetry install --no-root

# Expose the gRPC port
EXPOSE 50051

# Use our custom entrypoint script
ENTRYPOINT ["poetry", "run", "hyperion"]