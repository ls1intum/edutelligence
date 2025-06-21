# Hyperion Java gRPC Client

A Java client library for interacting with Hyperion via gRPC.

## 📦 Installation

### From GitHub Packages

Add the GitHub Packages repository and dependency to your `build.gradle`:

```gradle
repositories {
    mavenCentral()
    maven {
        name = "GitHubPackages"
        url = uri("https://maven.pkg.github.com/ls1intum/edutelligence")
        credentials {
            username = project.findProperty("gpr.user") ?: System.getenv("GITHUB_ACTOR")
            password = project.findProperty("gpr.key") ?: System.getenv("GITHUB_TOKEN")
        }
    }
}

dependencies {
    implementation 'de.tum.cit.aet.edutelligence:hyperion:0.1.0-SNAPSHOT'
}
```

### Authentication Setup

#### For Local Development

1. Create a `gradle.properties` file in your project root (copy from `gradle.properties.template`)
2. Get a GitHub Personal Access Token:
   - Go to [GitHub Settings > Tokens](https://github.com/settings/tokens)
   - Click "Generate new token" → "Generate new token (classic)"
   - Select scopes: `read:packages` (minimum), `write:packages` (if publishing)
3. Add your credentials to `gradle.properties`:

```properties
gpr.user=your-github-username
gpr.key=ghp_your-personal-access-token
```

#### For CI/CD

Use environment variables (automatically available in GitHub Actions):

- `GITHUB_ACTOR`: GitHub username
- `GITHUB_TOKEN`: Automatically provided GitHub token

## 🚀 Usage

```java
import de.tum.cit.aet.hyperion.HyperionServiceGrpc;
import de.tum.cit.aet.hyperion.HyperionProto;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;

public class HyperionClient {
    public static void main(String[] args) {
        // Create a channel to the Hyperion server
        ManagedChannel channel = ManagedChannelBuilder
            .forAddress("localhost", 8080)
            .usePlaintext()
            .build();
        
        // Create a blocking stub
        HyperionServiceGrpc.HyperionServiceBlockingStub stub = 
            HyperionServiceGrpc.newBlockingStub(channel);
        
        // Use the client
        // ... your gRPC calls here
        
        // Shutdown the channel
        channel.shutdown();
    }
}
```

## 🛠️ Development

### Prerequisites

- Java 17 or higher
- Gradle 8.0 or higher

### Building the Project

```bash
# Build the project
./gradlew build

# Build and publish to Maven Local
./gradlew buildClient

# Publish to GitHub Packages (requires authentication)
./gradlew publishToGitHubPackages
```

### Proto File Management

The project automatically copies the proto file from the main Hyperion project during build. The proto file is located at `../app/protos/hyperion.proto` and is copied to `proto/hyperion.proto`.

## 📋 Available Versions

### Snapshot Versions

Snapshot versions are automatically published on every push to `main` and `develop` branches:

- Format: `0.1.0-YYYYMMDDHHMMSS-{commit-sha}-SNAPSHOT`
- Use for development and testing
- Available at: [GitHub Packages](https://github.com/ls1intum/edutelligence/packages)
