# Hyperion: AI-Driven Programming Exercise Creation Assistance

**Hyperion** is a microservice designed to bring AI-driven intelligence to Learning Management Systems (LMSs), such as [Artemis](https://github.com/ls1intum/Artemis). Inspired by the Titan of light and enlightenment, Hyperion illuminates the process of creating engaging, effective programming exercises. It assists instructors by refining problem statements, generating code stubs, and providing context-aware suggestions — all while integrating seamlessly with an LMS and CI build agents for validation.

## Setup

### Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

### Installation

#### Poetry

Install Peotry, if you haven't already:

```bash
pip install poetry
```

Ensure that you are using poetry version 2.0.0 or higher.

```bash
poetry --version
```

If you have poetry < 2.0.0 installed, please run

```bash
poetry self update
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

To verify the server is running correctly, you can use the health check script:

```bash
poetry run health-check
```

This will test connectivity to the server and return server status information.

### Docker Compose

#### Production Deployment

To run the service in a production environment using Docker Compose:

```bash
cd docker
docker compose -f compose.hyperion.yaml up -d
```

This uses the pre-built image from the GitHub Container Registry.

#### Local Development

For local development or testing, use the local compose file which builds from your local source:

```bash
cd docker
docker compose -f compose.hyperion.local.yaml build
docker compose -f compose.hyperion.local.yaml up -d
```

The local compose file:
- Builds the image from your local source code
- Maps port 50051 directly to your host machine
- Sets default environment variables with fallbacks (e.g., OpenAI API keys)
- Includes health checks and logging configuration

To check the logs of the running container:

```bash
docker compose -f compose.hyperion.local.yaml logs
```

To check the health of a running Docker container:

```bash
docker compose -f compose.hyperion.local.yaml exec hyperion poetry run health-check
```

#### Environment Variables

The Docker Compose files support the following environment variables:

| Variable | Description | Default in Local Compose |
|----------|-------------|-----------------------|
| `MODEL_NAME` | OpenAI model to use | gpt-3.5-turbo |
| `OPENAI_API_KEY` | OpenAI API key | sk-dummy-key |
| `OPENAI_API_VERSION` | OpenAI API version | 2023-05-15 |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | empty |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | empty |
| `OLLAMA_BASIC_AUTH_USERNAME` | Ollama authentication username | empty |
| `OLLAMA_BASIC_AUTH_PASSWORD` | Ollama authentication password | empty |
| `OLLAMA_HOST` | Ollama host address | empty |

You can set these environment variables in your shell before running Docker Compose, or use a `.env` file.



## Generate gRPC stubs

The service uses gRPC for communication. If you make changes to the proto files, you'll need to regenerate the stubs:

```bash
poetry run generate-grpc
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
