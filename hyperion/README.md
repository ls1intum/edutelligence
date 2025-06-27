# Hyperion: AI-Driven Programming Exercise Creation Assistance

**Hyperion** is a gRPC microservice for AI-driven programming exercise creation, designed to integrate with Learning Management Systems like [Artemis](https://github.com/ls1intum/Artemis).

## Features

Hyperion provides an 8-step workflow for creating programming exercises:

1. **Define Boundary Conditions** - Establish exercise constraints and requirements
2. **Draft Problem Statement** - Generate initial exercise descriptions
3. **Create Solution Repository** - Generate complete solution code
4. **Create Template Repository** - Generate starter code for students
5. **Create Test Repository** - Generate automated test cases
6. **Finalize Problem Statement** - Refine and polish exercise descriptions
7. **Configure Grading** - Set up automated grading criteria
8. **Review and Refine** - Check for inconsistencies and improve content

### Available Services

- **Inconsistency Checking**: Analyze exercises for conflicts between problem statements, solution code, template code, and tests
- **Problem Statement Rewriting**: Improve and refine exercise descriptions using AI

## Setup

### Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

### Installation

#### Poetry

Install Poetry version >=2.0.0, if you haven't already:

```bash
pip install poetry
```

#### Dependencies

Activate the virtual environment and install the dependencies:

```bash
poetry env activate
poetry install
```

## Running the Service

The Hyperion service runs as a gRPC server that listens for requests from clients.

```bash
poetry run hyperion
```

By default, the server runs on `0.0.0.0:50051`. You can configure the host and port through environment variables.

### Health Check

To verify the server is running correctly, you can use the standard gRPC health probe:

```bash
# Using grpc_health_probe (if installed)
grpc_health_probe -addr=localhost:50051

# Or using grpcurl
grpcurl -plaintext localhost:50051 grpc.health.v1.Health/Check
```

The server implements the standard gRPC health checking protocol.

### Docker Compose

#### Production Deployment

To run the service in a production environment using Docker Compose:

```bash
docker compose -f compose.yaml up -d
```

This uses the pre-built image from the GitHub Container Registry and exposes the service on port **8080**.

#### Local Development

For local development or testing, use the local compose file which builds from your local source:

```bash
docker compose -f compose.local.yaml build
docker compose -f compose.local.yaml up -d
```

The local compose file:

- Builds the image from your local source code
- Maps port **50051** directly to your host machine
- Uses environment variables from `.env` file
- Includes health checks and logging configuration

To check the logs of the running container:

```bash
docker compose -f compose.local.yaml logs
```

To check the health of a running Docker container:

```bash
# Using docker compose health check
docker compose -f compose.local.yaml ps

# Or directly test the gRPC service
grpc_health_probe -addr=localhost:50051
```

#### Environment Variables

The Docker Compose files support the following environment variables:

| Variable                     | Description                    | Example Value            |
| ---------------------------- | ------------------------------ | ------------------------ |
| `MODEL_NAME`                 | OpenAI model to use            | gpt-3.5-turbo            |
| `OPENAI_API_KEY`             | OpenAI API key                 | sk-your-key-here         |
| `OPENAI_API_VERSION`         | OpenAI API version             | 2023-05-15               |
| `AZURE_OPENAI_ENDPOINT`      | Azure OpenAI endpoint URL      | your.openai.azure.com   |
| `AZURE_OPENAI_API_KEY`       | Azure OpenAI API key           | your-azure-key          |
| `OLLAMA_BASIC_AUTH_USERNAME` | Ollama authentication username | username                 |
| `OLLAMA_BASIC_AUTH_PASSWORD` | Ollama authentication password | password                 |
| `OLLAMA_HOST`                | Ollama host address            | localhost:11434          |
| `TLS_ENABLED`                | Enable TLS (production)        | true/false               |
| `TLS_CERT_PATH`              | TLS certificate path           | /certs/server.crt        |
| `TLS_KEY_PATH`               | TLS private key path           | /certs/server.key        |

You can set these environment variables in your shell before running Docker Compose, or use a `.env` file.

### TLS Configuration

Enable TLS for production:

#### 1. Generate Certificates

For development/testing, use the provided script:

```bash
./scripts/generate-certs.sh
```

For production, obtain certificates from a proper CA (Let's Encrypt, corporate CA, etc.) and place them in the `./certs/` directory.

#### 2. Configure Environment

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit the `.env` file and set:

```bash
TLS_ENABLED=true
TLS_CERT_PATH=/certs/server.crt
TLS_KEY_PATH=/certs/server.key
TLS_CA_PATH=/certs/ca.crt  # For client certificate verification (mTLS)
```

#### 3. Deploy with TLS

```bash
docker compose -f compose.yaml up -d
```

#### 4. Verify TLS Connection

```bash
# Check health with certificate verification
grpcurl -cacert ./certs/ca.crt your-domain.com:50051 grpc.health.v1.Health/Check

# Check specific service
grpcurl -cacert ./certs/ca.crt your-domain.com:50051 hyperion.ReviewAndRefine/CheckInconsistencies

# With client certificate (mTLS)
grpcurl -cacert ./certs/ca.crt -cert ./certs/client.crt -key ./certs/client.key \
        your-domain.com:8080 grpc.health.v1.Health/Check
```

## Artemis Integration

Hyperion integrates with Artemis through a simple proto file synchronization approach. The proto file from Hyperion is copied to Artemis where gRPC client stubs are generated as part of the Artemis build process.

### Proto File Synchronization

To synchronize the Hyperion proto file with Artemis:

```bash
# Synchronize proto file to Artemis
poetry run sync-proto-artemis

# Sync to a specific path
poetry run sync-proto-artemis --artemis-path /path/to/artemis

# Dry run to see what would be copied
poetry run sync-proto-artemis --dry-run
```

This command:
1. Copies `app/protos/hyperion.proto` to `{artemis_path}/src/main/proto/hyperion.proto`
2. Ensures the target directory exists
3. Validates the proto file syntax
4. Reports the synchronization status


## Generate gRPC stubs

The service uses gRPC for communication. If you make changes to the proto files, you'll need to regenerate the stubs:

```bash
poetry run generate-proto
```

The generated stubs will be placed in the `app/grpc` directory.

## Formatting

### Black

To format the code, run the following command:

```bash
poetry run black .
```

### Flake8

To lint the code, run the following command:

```bash
poetry run flake8 .
```
