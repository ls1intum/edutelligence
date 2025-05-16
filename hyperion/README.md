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

To run the service using Docker Compose:

```bash
cd docker
docker-compose -f compose.hyperion.yaml up -d
```

To check the health of a running Docker container:


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
