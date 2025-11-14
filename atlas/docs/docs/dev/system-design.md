---
title: "System Design"
description: "Understanding AtlasML's architecture and component interactions"
sidebar_position: 2
---

# System Design

This guide explains how AtlasML is architected, how components interact, and the request/response flow through the system.

---

## High-Level Architecture

```mermaid
graph TB
    Client[Client Application]
    API[FastAPI Application]
    Middleware[Request Logging Middleware]
    Auth[Authentication Layer]
    Routers[API Routers]
    ML[ML Pipelines]
    Weaviate[(Weaviate Vector DB)]
    OpenAI[OpenAI API]

    Client -->|HTTP Request| API
    API --> Middleware
    Middleware --> Auth
    Auth --> Routers
    Routers --> ML
    ML --> Weaviate
    ML --> OpenAI
    Weaviate -->|Vector Search| ML
    ML --> Routers
    Routers --> Middleware
    Middleware -->|HTTP Response| Client

    style API fill:#4A90E2
    style Weaviate fill:#FF6B6B
    style ML fill:#4ECDC4
```

### Key Components

1. **FastAPI Application** (`app.py`): Entry point, middleware, and router registration
2. **Routers**: Handle specific API endpoints (health, competency)
3. **ML Pipelines**: Orchestrate machine learning workflows
4. **Weaviate Client**: Interface to the vector database
5. **Configuration**: Environment-based settings management
6. **Authentication**: API key validation

---

## Request Flow Diagram

Here's what happens when a client makes a request to AtlasML:

```mermaid
sequenceDiagram
    participant Client
    participant Middleware
    participant Auth
    participant Router
    participant ML Pipeline
    participant Weaviate
    participant OpenAI

    Client->>Middleware: POST /api/v1/competency/suggest
    Middleware->>Middleware: Log request (method, path, body)
    Middleware->>Auth: Validate Authorization header
    Auth->>Auth: Check API key against config

    alt Invalid API Key
        Auth-->>Client: 401 Unauthorized
    else Valid API Key
        Auth->>Router: Pass to competency router
        Router->>ML Pipeline: Call suggest_competencies()
        ML Pipeline->>OpenAI: Generate embedding for description
        OpenAI-->>ML Pipeline: Return embedding vector
        ML Pipeline->>Weaviate: Search similar competencies
        Weaviate-->>ML Pipeline: Return matching competencies
        ML Pipeline-->>Router: Return competency list
        Router-->>Middleware: Return 200 + response body
        Middleware->>Middleware: Log response (status, duration)
        Middleware-->>Client: Return response
    end
```

### Flow Breakdown

1. **Request Reception**: Client sends HTTP request to FastAPI
2. **Middleware Processing**: `RequestLoggingMiddleware` logs request details
3. **Authentication**: `TokenValidator` checks the `Authorization` header
4. **Routing**: FastAPI routes to appropriate endpoint handler
5. **Business Logic**: Router calls ML pipeline or service layer
6. **Database Operations**: Weaviate client performs vector operations
7. **External API Calls**: OpenAI generates embeddings (if configured)
8. **Response Building**: Pydantic models serialize the response
9. **Middleware Logging**: Duration and status are logged
10. **Response Return**: Client receives JSON response

---

## Application Initialization

### Startup Sequence

When you run `uvicorn atlasml.app:app`, here's what happens:

```mermaid
graph TD
    A[uvicorn starts] --> B[Import app.py]
    B --> C[Load Configuration]
    C --> D[Initialize Sentry optional]
    D --> E[Create FastAPI app]
    E --> F[Register Middleware]
    F --> G[Register Exception Handlers]
    G --> H[Register Routers]
    H --> I[Lifespan: startup event]
    I --> J[Initialize Weaviate Client]
    J --> K[Check Weaviate Connection]
    K --> L[Ensure Collections Exist]
    L --> M[Application Ready]

    style M fill:#4ECDC4
```

### Lifespan Events

The `lifespan` context manager in `app.py` handles startup and shutdown:

```python
@asynccontextmanager
async def lifespan(app):
    # Startup
    logger.info("🚀 Starting AtlasML API...")
    logger.info(f"🔌 Weaviate client status: {'Connected' if get_weaviate_client().is_alive() else 'Disconnected'}")
    logger.info("✅ Weaviate collections initialized")

    yield  # Application is running

    # Shutdown
    logger.info("👋 Shutting down AtlasML API...")
    get_weaviate_client().close()
```

**Startup tasks:**
- Check Weaviate connectivity
- Initialize collections if they don't exist
- Log system status

**Shutdown tasks:**
- Gracefully close Weaviate connection
- Release resources

---

## Middleware Stack

Middleware processes all requests and responses. AtlasML uses:

### 1. RequestLoggingMiddleware

Located in `app.py`, this middleware:

```python
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Log request
        logger.info(f"→ {request.method} {request.url.path}")
        if request.method == "POST":
            body = await request.body()
            logger.info(f"📦 Request body: {body.decode()[:200]}")

        # Process request
        response = await call_next(request)

        # Log response
        duration = time.time() - start_time
        logger.info(f"← {response.status_code} ({duration:.3f}s)")

        return response
```

**What it does:**
- Logs incoming request method and path
- Logs POST request bodies (first 200 chars)
- Measures request processing time
- Logs response status and duration

**Why it's useful:**
- Debugging: See all API activity
- Performance: Identify slow endpoints
- Monitoring: Track API usage patterns

### Execution Order

```mermaid
graph LR
    A[Request] --> B[RequestLoggingMiddleware]
    B --> C[Auth Dependencies]
    C --> D[Router Handler]
    D --> E[Response]
    E --> F[RequestLoggingMiddleware]
    F --> G[Client]

    style B fill:#FFD93D
    style F fill:#FFD93D
```

Middleware wraps the entire request/response cycle.

---

## Dependency Injection

AtlasML uses FastAPI's dependency injection for:

### 1. Authentication (`TokenValidator`)

```python
class TokenValidator:
    def __init__(self, api_keys: List[APIKeyConfig] = Depends(get_api_keys)):
        self.api_keys = api_keys

    async def __call__(self, api_key: str = Depends(_get_api_key)) -> APIKeyConfig:
        for key in self.api_keys:
            if key.token == api_key:
                return key
        raise HTTPException(status_code=401, detail="Invalid API key")
```

**How it works:**
1. `Depends(get_api_keys)` injects configured API keys from settings
2. `Depends(_get_api_key)` extracts the `Authorization` header
3. Validates the key against configured keys
4. Raises 401 if invalid, continues if valid

**Usage in routers:**
```python
@router.post("/suggest", dependencies=[Depends(TokenValidator)])
async def suggest_competencies(request: SuggestCompetencyRequest):
    # Only runs if authentication succeeds
    ...
```

### 2. Weaviate Client (`get_weaviate_client`)

```python
def get_weaviate_client(weaviate_settings: WeaviateSettings = None) -> WeaviateClient:
    return WeaviateClientSingleton.get_instance(weaviate_settings)
```

**Singleton Pattern:**
- Only one Weaviate client instance is created
- Reused across all requests
- Connection pooling handled by the SDK

**Why singleton?**
- Efficient: Avoid reconnection overhead
- Safe: Weaviate SDK is thread-safe
- Simple: No need to manage connections

---

## Component Interaction

### Competency Suggestion Flow

Here's a detailed look at how the `/api/v1/competency/suggest` endpoint works:

```mermaid
sequenceDiagram
    participant Client
    participant Router
    participant PipelineWorkflows
    participant EmbeddingGenerator
    participant OpenAI
    participant WeaviateClient
    participant Weaviate DB

    Client->>Router: POST /suggest {description, course_id}
    Router->>PipelineWorkflows: get_competency_suggestions()

    PipelineWorkflows->>EmbeddingGenerator: generate_embeddings_openai(description)
    EmbeddingGenerator->>OpenAI: Create embedding
    OpenAI-->>EmbeddingGenerator: Return vector [1536 dims]
    EmbeddingGenerator-->>PipelineWorkflows: Return embedding

    PipelineWorkflows->>WeaviateClient: get_embeddings_by_property("course_id", 1)
    WeaviateClient->>Weaviate DB: Query with filter
    Weaviate DB-->>WeaviateClient: Return competency vectors
    WeaviateClient-->>PipelineWorkflows: Return competencies

    PipelineWorkflows->>PipelineWorkflows: compute_cosine_similarity()
    PipelineWorkflows->>PipelineWorkflows: rank_by_similarity()
    PipelineWorkflows-->>Router: Return top suggestions
    Router-->>Client: 200 OK + competencies
```

### File Locations

| Component | File |
|-----------|------|
| Router | `atlasml/routers/competency.py` |
| ML Pipeline | `atlasml/ml/pipeline_workflows.py` |
| Embedding Generator | `atlasml/ml/embeddings.py` |
| Weaviate Client | `atlasml/clients/weaviate.py` |
| Similarity | `atlasml/ml/similarity_measures.py` |

---

## Configuration Management

### Settings Hierarchy

```mermaid
graph TD
    A[Environment Variables] --> B[Settings.get_settings]
    B --> C{use_defaults?}
    C -->|Yes| D[Default Settings]
    C -->|No| E[Parse .env file]
    E --> F[Validate with Pydantic]
    F --> G[Return Settings object]
    D --> G
    G --> H[SettingsProxy]
    H --> I[Application uses settings]

    style G fill:#4ECDC4
```

### Settings Model

```python
class Settings(BaseModel):
    api_keys: list[APIKeyConfig]       # API authentication keys
    weaviate: WeaviateSettings         # Weaviate connection config
    sentry_dsn: str | None = None      # Optional Sentry DSN
    env: str = "development"           # Environment name
```

### Configuration Sources

1. **Environment Variables** (`.env` file):
   ```bash
   ATLAS_API_KEYS=["key1","key2"]
   WEAVIATE_HOST=localhost
   WEAVIATE_PORT=8085
   ```

2. **Default Settings** (for tests):
   ```python
   Settings._get_default_settings()
   ```

3. **SettingsProxy** (global access):
   ```python
   from atlasml.config import settings

   print(settings.weaviate.host)  # "localhost"
   ```

---

## Error Handling

### Exception Flow

```mermaid
graph TD
    A[Exception Raised] --> B{Exception Type}
    B -->|RequestValidationError| C[validation_exception_handler]
    B -->|HTTPException| D[Default Handler]
    B -->|WeaviateError| E[Caught by router]
    B -->|Unhandled| F[500 Internal Server Error]

    C --> G[422 Unprocessable Entity]
    D --> H[Return status code]
    E --> I[500 with error details]
    F --> I

    style G fill:#FF6B6B
    style H fill:#FFD93D
    style I fill:#FF6B6B
```

### Custom Exception Handler

```python
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"❌ Validation error for {request.method} {request.url.path}")
    logger.error(f"❌ Validation details: {exc.errors()}")
    logger.error(f"❌ Request body was: {await request.body()}")

    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "body": (await request.body()).decode()
        }
    )
```

**What it does:**
- Logs validation failures for debugging
- Returns detailed error information
- Includes the invalid request body

---

## Data Flow Architecture

### Write Operations

```mermaid
graph LR
    A[Client] -->|POST /save| B[Router]
    B --> C[Validate Request]
    C --> D{Operation Type}
    D -->|UPDATE| E[Generate Embeddings]
    D -->|DELETE| F[Delete from Weaviate]
    E --> G[Store in Weaviate]
    G --> H[Return Success]
    F --> H
    H --> A

    style E fill:#4ECDC4
    style G fill:#FF6B6B
```

### Read Operations

```mermaid
graph LR
    A[Client] -->|POST /suggest| B[Router]
    B --> C[Generate Query Embedding]
    C --> D[Search Weaviate]
    D --> E[Rank Results]
    E --> F[Return Top N]
    F --> A

    style D fill:#FF6B6B
    style E fill:#4ECDC4
```

---

## Scalability Considerations

### Current Architecture

- **Single Instance**: One FastAPI process
- **Singleton Client**: One Weaviate connection per instance
- **Synchronous ML**: Embeddings generated on request

### Scaling Options

1. **Horizontal Scaling**:
   - Run multiple FastAPI instances
   - Load balancer distributes requests
   - Weaviate handles concurrent connections

2. **Async Operations**:
   - Use async OpenAI client
   - Background tasks for long operations
   - Celery for distributed task queue

3. **Caching**:
   - Redis for embedding cache
   - Reduce API calls to OpenAI
   - Faster response times

---

## Security Architecture

### Authentication Flow

```mermaid
graph TD
    A[Request with Authorization header] --> B{Header present?}
    B -->|No| C[401 Unauthorized]
    B -->|Yes| D{Valid API key?}
    D -->|No| C
    D -->|Yes| E[Extract API key config]
    E --> F[Continue to router]

    style C fill:#FF6B6B
    style F fill:#4ECDC4
```

### Security Layers

1. **API Key Authentication**:
   - Simple token-based auth
   - Keys configured in environment
   - No user sessions or cookies

2. **Input Validation**:
   - Pydantic models validate all inputs
   - Type checking at runtime
   - Prevent injection attacks

3. **CORS** (if needed):
   - Configure allowed origins
   - Restrict cross-origin requests

:::warning Security Note
API keys are transmitted in plaintext headers. Always use HTTPS in production to encrypt transmission.
:::

---

## Monitoring & Observability

### Logging Strategy

```python
# Different log levels
logger.info("Normal operations")      # General info
logger.warning("Potential issues")     # Warnings
logger.error("Errors occurred")        # Errors
logger.debug("Detailed debugging")     # Debug mode only
```

### What Gets Logged

1. **Startup/Shutdown**: Application lifecycle
2. **Requests**: Method, path, body (POST)
3. **Responses**: Status code, duration
4. **Errors**: Exception details, stack traces
5. **Weaviate**: Connection status, query info
6. **ML**: Embedding generation, similarity scores

### Sentry Integration

When `ENV=production` and `SENTRY_DSN` is set:

```python
sentry_sdk.init(
    dsn=settings.sentry_dsn,
    environment=settings.env,
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)
```

**What Sentry captures:**
- Unhandled exceptions
- Error traces
- Performance data
- Request context

---

## Next Steps

Now that you understand the architecture:

- **[Modules Reference](./code-reference/modules.md)**: Dive deep into each code module
- **[REST API Framework](./code-reference/rest-api.md)**: Learn about FastAPI patterns
- **[Middleware](./code-reference/middleware.md)**: Understand request processing
- **[Weaviate Integration](./code-reference/weaviate.md)**: Master the vector database

:::tip
Use the [FastAPI documentation](http://localhost:8000/docs) to explore the live API while reading these docs!
:::
