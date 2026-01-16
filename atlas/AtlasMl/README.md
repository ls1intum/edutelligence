# **AtlasML**

AtlasML is a FastAPI-based microservice that provides competency-centric ML features through a REST API. It integrates with a Weaviate vector database for embedding storage and retrieval.

---

## **Features**

- FastAPI framework with async support
- Weaviate vector database integration
- Azure OpenAI embeddings
- Poetry for dependency management
- Comprehensive test suite with pytest
- API key authentication

---

## **Local Development Setup**

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for Weaviate)
- [Poetry](https://python-poetry.org/docs/#installation) (for Python dependencies)
- Python 3.13+

### 1. Clone the Repository

```bash
git clone <repository_url>
cd atlas/AtlasMl
```

### 2. Start Local Weaviate Instance

AtlasML requires a running Weaviate instance. For local development, use the development Docker Compose file:

```bash
# From the atlas directory (parent of AtlasMl)
cd ..
docker compose -f docker-compose.dev.yml up -d
```

This starts:
- Weaviate on `http://localhost:8085` (REST API, no authentication required)
- Weaviate gRPC on `localhost:50051` (required by Python client v4)
- Multi2vec-CLIP on `http://localhost:8081` (for embeddings)

**Verify Weaviate is running:**
```bash
curl http://localhost:8085/v1/.well-known/ready
# Should return: {"status":"ok"}
```

### 3. Install Python Dependencies

```bash
poetry install
```

### 4. Configure Environment Variables

Create a `.env` file based on the example:

```bash
cp .env.example .env
```

**Required variables for local development:**
```bash
# AtlasML Authentication (for API endpoints)
ATLAS_API_KEYS=dev-test-key

# Local Weaviate (no authentication needed)
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085
WEAVIATE_GRPC_PORT=50051

# Azure OpenAI (required for embeddings)
OPENAI_API_KEY=your-azure-openai-key
OPENAI_API_URL=https://your-instance.openai.azure.com

# Optional
SENTRY_DSN=
ENV=development
```

> **Note:** You need valid Azure OpenAI credentials for the embedding functionality to work. Contact your team for access.

### 5. Run the Application

```bash
poetry run uvicorn atlasml.app:app --reload
```

The API will be available at `http://localhost:8000`

**Test the API:**
```bash
# Health check (no auth required)
curl http://localhost:8000/api/v1/health

# Protected endpoint (requires API key)
curl -H "Authorization: dev-test-key" \
  http://localhost:8000/api/v1/competencies/suggest
```

### 6. Run Tests

```bash
# Run all tests
poetry run pytest -v

# Run specific test file
poetry run pytest tests/routers/test_competency.py -v

# Run with coverage
poetry run pytest --cov=atlasml --cov-report=html
```

### 7. Code Quality

```bash
# Check code style
poetry run ruff check .

# Format code
poetry run black .
```

---

## **Project Structure**

```
atlasml/
├── atlasml/
│   ├── app.py              # FastAPI application setup
│   ├── config.py           # Settings and configuration
│   ├── dependencies.py     # FastAPI dependencies (auth)
│   ├── routers/            # API endpoints
│   │   ├── health.py       # Health check endpoint
│   │   └── competency.py   # Competency endpoints
│   ├── models/             # Pydantic models
│   │   └── competency.py   # Request/response models
│   ├── clients/            # External service clients
│   │   └── weaviate.py     # Weaviate client wrapper
│   └── ml/                 # ML workflows
│       └── pipeline_workflows.py
├── tests/                  # Test suite
├── pyproject.toml          # Poetry dependencies
└── .env.example            # Environment template
```

---

## **Development Workflow**

### Starting Work

```bash
# 1. Start infrastructure (from atlas directory)
cd /path/to/atlas
docker compose -f docker-compose.dev.yml up -d

# 2. Start AtlasML (from AtlasMl directory)
cd AtlasMl
poetry shell
uvicorn atlasml.app:app --reload
```

### Stopping Work

```bash
# Stop the application (Ctrl+C)

# Stop infrastructure (from atlas directory)
cd ..
docker compose -f docker-compose.dev.yml down
```

### Reset Weaviate Data

If you need to reset your local Weaviate database:

```bash
# From atlas directory
docker compose -f docker-compose.dev.yml down -v  # Remove volumes
docker compose -f docker-compose.dev.yml up -d    # Start fresh
```

---

## **Troubleshooting**

### Weaviate Connection Issues

**Problem:** `WeaviateConnectionError: Could not connect to Weaviate server`

**Solutions:**
1. Check if Weaviate is running: `docker ps | grep weaviate`
2. Verify port 8085 is not in use: `lsof -i :8085`
3. Check Weaviate logs (from atlas directory): `docker compose -f docker-compose.dev.yml logs weaviate`
4. Try restarting (from atlas directory): `docker compose -f docker-compose.dev.yml restart weaviate`

### Azure OpenAI Issues

**Problem:** `OpenAI API key is required`

**Solution:** Set valid Azure OpenAI credentials in `.env`:
```bash
OPENAI_API_KEY=<your-key>
OPENAI_API_URL=https://<your-instance>.openai.azure.com
```

### Test Failures

**Problem:** Tests fail with Weaviate connection errors

**Solution:** Tests use mocked Weaviate, no real connection needed. If tests fail:
1. Ensure all dependencies are installed: `poetry install`
2. Check environment variables are set (see `tests/conftest.py`)
3. Run with verbose output: `poetry run pytest -vv`

---

## **Production Deployment**

For production deployment with HTTPS and API key authentication, see:
- [AtlasML Admin Guide](../docs/docs/admin/atlasml-installation.md)
- [Weaviate Production Setup](../../weaviate/README.md)

---

## **Additional Documentation**

- **API Reference:** See [docs/dev/atlasml/api.md](../docs/docs/dev/atlasml/api.md)
- **Settings & Auth:** See [docs/dev/atlasml/settings_auth.md](../docs/docs/dev/atlasml/settings_auth.md)
- **Weaviate Client:** See [docs/dev/atlasml/weaviate.md](../docs/docs/dev/atlasml/weaviate.md)

## License
