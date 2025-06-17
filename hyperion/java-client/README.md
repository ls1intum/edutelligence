# Hyperion Java gRPC Client

This is the Java client library for the Hyperion gRPC service.

## Overview

The Hyperion Java client provides:

- Generated Java classes from the Hyperion protobuf definitions
- gRPC client stubs for all Hyperion services
- Seamless integration with Java applications

## Prerequisites

- Java 17 or higher

## Building the Java Client

From the main Hyperion project directory:

```bash
# Generate the Java client library
poetry run build-java-client
```

This command will:

1. Copy the `hyperion.proto` file to the Java client project
2. Generate Java classes from the protobuf definitions
3. Build the Java library
4. Publish the library to your local Maven repository

## Consuming the Java Client

### In Gradle Projects

Add the dependency to your `build.gradle`:

```gradle
dependencies {
    implementation 'de.tum.cit.aet:hyperion:0.1.0-SNAPSHOT'
    
    // Additional gRPC runtime dependencies if not already present
    implementation 'io.grpc:grpc-netty-shaded:1.71.0'
    implementation 'io.grpc:grpc-protobuf:1.71.0'
    implementation 'io.grpc:grpc-stub:1.71.0'
}
```

### In Maven Projects

Add to your `pom.xml`:

```xml
<dependency>
    <groupId>de.tum.cit.aet</groupId>
    <artifactId>hyperion</artifactId>
    <version>0.1.0-SNAPSHOT</version>
</dependency>
```

## Usage Examples

### Basic Client Setup

```java
import de.tum.cit.aet.hyperion.*;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;

public class HyperionClient {
    private final ManagedChannel channel;
    private final HealthGrpc.HealthBlockingStub healthStub;
    private final VerifyConfigurationGrpc.VerifyConfigurationBlockingStub verifyStub;
    
    public HyperionClient(String host, int port) {
        this.channel = ManagedChannelBuilder.forAddress(host, port)
            .usePlaintext() // Use TLS in production
            .build();
            
        this.healthStub = HealthGrpc.newBlockingStub(channel);
        this.verifyStub = VerifyConfigurationGrpc.newBlockingStub(channel);
    }
    
    public void shutdown() {
        channel.shutdown();
    }
}
```

### Health Check

```java
public boolean checkHealth() {
    try {
        PingRequest request = PingRequest.newBuilder()
            .setClientId("artemis-client")
            .build();
            
        PingResponse response = healthStub.ping(request);
        
        System.out.println("Server status: " + response.getStatus());
        System.out.println("Server version: " + response.getVersion());
        
        return "OK".equals(response.getStatus());
    } catch (Exception e) {
        System.err.println("Health check failed: " + e.getMessage());
        return false;
    }
}
```

### Inconsistency Check

```java
public String checkExerciseInconsistencies(
    String problemStatement,
    Repository solutionRepo,
    Repository templateRepo,
    Repository testRepo) {
    
    InconsistencyCheckRequest request = InconsistencyCheckRequest.newBuilder()
        .setProblemStatement(problemStatement)
        .setSolutionRepository(solutionRepo)
        .setTemplateRepository(templateRepo)
        .setTestRepository(testRepo)
        .build();
        
    InconsistencyCheckResponse response = verifyStub.checkInconsistencies(request);
    return response.getInconsistencies();
}
```

### Building Repository Objects

```java
public Repository createRepository(Map<String, String> fileContents) {
    Repository.Builder repoBuilder = Repository.newBuilder();
    
    for (Map.Entry<String, String> entry : fileContents.entrySet()) {
        RepositoryFile file = RepositoryFile.newBuilder()
            .setPath(entry.getKey())
            .setContent(entry.getValue())
            .build();
        repoBuilder.addFiles(file);
    }
    
    return repoBuilder.build();
}
```

### Complete Example

```java
import de.tum.cit.aet.hyperion.*;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import java.util.Map;
import java.util.HashMap;

public class ArtemisHyperionIntegration {
    private final HyperionClient client;
    
    public ArtemisHyperionIntegration(String hyperionHost, int hyperionPort) {
        this.client = new HyperionClient(hyperionHost, hyperionPort);
    }
    
    public boolean validateExercise(ProgrammingExercise exercise) {
        // Check if Hyperion is available
        if (!client.checkHealth()) {
            throw new RuntimeException("Hyperion service is not available");
        }
        
        // Perform inconsistency check
        String inconsistencies = client.checkExerciseInconsistencies(
            exercise.getProblemStatement(),
            exercise.getSolutionRepository(),
            exercise.getTemplateRepository(),
            exercise.getTestRepository()
        );
        
        if (!inconsistencies.isEmpty()) {
            System.out.println("Exercise inconsistencies found: " + inconsistencies);
            return false;
        }
        
        return true;
    }
    
    public void close() {
        client.shutdown();
    }
}
```

## Available Services

The generated client provides stubs for all Hyperion services:

### Core Services

- `HealthGrpc` - Health checking and server status
- `VerifyConfigurationGrpc` - Exercise validation and inconsistency checking

### Exercise Creation Services

- `DefineBoundaryConditionGrpc` - Step 1: Define boundary conditions
- `DraftProblemStatementGrpc` - Step 2: Create draft problem statement
- `CreateSolutionRepositoryGrpc` - Step 3: Create solution repository
- `CreateTemplateRepositoryGrpc` - Step 4: Create template repository
- `CreateTestRepositoryGrpc` - Step 5: Create test repository
- `FinalizeProblemStatementGrpc` - Step 6: Finalize problem statement
- `ConfigureGradingGrpc` - Step 7: Configure grading
- `VerifyConfigurationGrpc` - Step 8: Verify configuration

## Data Models

Key protobuf message classes available:

- `ProgrammingExercise` - Complete exercise definition
- `Repository` - Collection of files
- `RepositoryFile` - Individual file with path and content
- `ProgrammingLanguage` - Enum of supported languages
- `ProjectType` - Enum of supported project types
- `PingRequest/PingResponse` - Health check messages
- `InconsistencyCheckRequest/InconsistencyCheckResponse` - Validation messages

## Development Workflow

### When Hyperion Proto Changes

1. Update the proto file in the main Hyperion project
2. Rebuild the Java client:

   ```bash
   cd hyperion/
   poetry run build-java-client
   ```

3. The updated library will be available in your local Maven repository
4. Update your consuming application's dependency version if needed

### Version Management

The client library version is managed in `build.gradle`:

- Group ID: `de.tum.cit.aet`
- Artifact ID: `hyperion`
- Version: `0.1.0-SNAPSHOT` (update as needed)

## Configuration

### Connection Settings

Configure the gRPC channel based on your deployment:

```java
// Development (local)
ManagedChannel channel = ManagedChannelBuilder
    .forAddress("localhost", 8080)
    .usePlaintext()
    .build();

// Production (with TLS)
ManagedChannel channel = ManagedChannelBuilder
    .forAddress("hyperion.example.com", 443)
    .useTransportSecurity()
    .build();
```

### Timeouts and Retries

```java
// Configure timeouts
HealthGrpc.HealthBlockingStub stub = HealthGrpc.newBlockingStub(channel)
    .withDeadlineAfter(30, TimeUnit.SECONDS);
```

## Troubleshooting

### Common Issues

1. **Proto file not found**
   - Ensure you've run `poetry run build-java-client` from the Hyperion project
   - Check that `proto/hyperion.proto` exists in the Java client directory

2. **Dependency conflicts**
   - Ensure gRPC versions are compatible across your project
   - Use the same protobuf version as the generated client

3. **Connection issues**
   - Verify Hyperion server is running and accessible
   - Check firewall and network configuration
   - Ensure correct host and port settings

### Gradle Issues

```bash
# Clean and rebuild
./gradlew clean build

# Check dependencies
./gradlew dependencies

# Publish to local Maven repo
./gradlew publishToMavenLocal
```

## Contributing

When modifying the Java client:

1. Update proto definitions in the main Hyperion project first
2. Rebuild the client library
3. Update this documentation as needed
4. Test integration with consuming applications

## License

This project follows the same license as the main Hyperion project.
