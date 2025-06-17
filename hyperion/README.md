# Hyperion: AI-Driven Programming Exercise Creation Assistance

**Hyperion** is a gRPC microservice for AI-driven programming exercise creation, designed to integrate with Learning Management Systems like [Artemis](https://github.com/ls1intum/Artemis).

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

| Variable                     | Description                    | Default in Local Compose |
| ---------------------------- | ------------------------------ | ------------------------ |
| `MODEL_NAME`                 | OpenAI model to use            | gpt-3.5-turbo            |
| `OPENAI_API_KEY`             | OpenAI API key                 | sk-dummy-key             |
| `OPENAI_API_VERSION`         | OpenAI API version             | 2023-05-15               |
| `AZURE_OPENAI_ENDPOINT`      | Azure OpenAI endpoint URL      | empty                    |
| `AZURE_OPENAI_API_KEY`       | Azure OpenAI API key           | empty                    |
| `OLLAMA_BASIC_AUTH_USERNAME` | Ollama authentication username | empty                    |
| `OLLAMA_BASIC_AUTH_PASSWORD` | Ollama authentication password | empty                    |
| `OLLAMA_HOST`                | Ollama host address            | empty                    |

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
cp .env.production .env
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
docker-compose -f docker/compose.hyperion.yaml -f docker/compose.proxy.yaml up -d
```

#### 4. Verify TLS Connection

```bash
# With certificate verification
grpcurl -cacert ./certs/ca.crt your-domain.com:50051 hyperion.Health/Ping

# With client certificate (mTLS)
grpcurl -cacert ./certs/ca.crt -cert ./certs/client.crt -key ./certs/client.key \
        your-domain.com:50051 hyperion.Health/Ping
```

## Java Client

Hyperion provides a Java gRPC client library for integration with Java applications like Artemis.

### Building the Java Client

To generate and build the Java client library:

```bash
cd java-client
./gradlew buildClient
```

This single command will automatically:

1. Copy the `hyperion.proto` file from the main project
2. Generate Java classes from the protobuf definitions
3. Build the Java library using Gradle
4. Publish the library to your local Maven repository

### Using the Java Client

Add the dependency to your Java project:

**Gradle:**

```gradle
dependencies {
    implementation 'de.tum.cit.aet:hyperion:0.1.0-SNAPSHOT'
}
```

**Maven:**

```xml
<dependency>
    <groupId>de.tum.cit.aet</groupId>
    <artifactId>hyperion</artifactId>
    <version>0.1.0-SNAPSHOT</version>
</dependency>
```

### Basic Usage

#### Development (Plaintext)

```java
import de.tum.cit.aet.hyperion.*;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;

// Create client for development
ManagedChannel channel = ManagedChannelBuilder
    .forAddress("localhost", 50051)
    .usePlaintext()
    .build();

HealthGrpc.HealthBlockingStub healthStub = HealthGrpc.newBlockingStub(channel);

// Health check
PingResponse response = healthStub.ping(
    PingRequest.newBuilder()
        .setClientId("artemis-client")
        .build()
);
```

#### Production (TLS)

```java
import de.tum.cit.aet.hyperion.*;
import io.grpc.ManagedChannel;
import io.grpc.netty.NettyChannelBuilder;

// Create client for production with TLS
ManagedChannel channel = NettyChannelBuilder
    .forAddress("hyperion.yourdomain.com", 50051)
    .useTransportSecurity() // Enable TLS
    .build();

HealthGrpc.HealthBlockingStub healthStub = HealthGrpc.newBlockingStub(channel);

// Health check with timeout
PingResponse response = healthStub
    .withDeadlineAfter(30, TimeUnit.SECONDS)
    .ping(PingRequest.newBuilder()
        .setClientId("artemis-client")
        .build());
```

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
