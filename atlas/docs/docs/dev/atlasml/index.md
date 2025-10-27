---
title: "AtlasML Overview & Getting Started"
description: "Complete guide to setting up and running AtlasML locally"
sidebar_position: 1
---

# AtlasML Overview & Getting Started

## What is AtlasML?

AtlasML is a **FastAPI-based microservice** that provides machine learning capabilities for competency-based learning. It uses:

- **FastAPI** for the REST API framework
- **Weaviate** as a vector database for embeddings and semantic search
- **OpenAI/SentenceTransformers** for generating text embeddings
- **scikit-learn** for clustering and ML algorithms
- **Poetry** for dependency management

### Key Features

- **Competency Suggestions**: Suggest relevant competencies based on textual descriptions
- **Semantic Search**: Find similar competencies using vector embeddings
- **Relationship Generation**: Automatically suggest relationships between competencies
- **Clustering**: Group related competencies into semantic clusters
- **Exercise Management**: Store and query exercises with competency associations

---

## Prerequisites

Before you begin, ensure you have the following installed:

### Required

- **Python 3.13+**: [Download Python](https://www.python.org/downloads/)
- **Poetry**: Package manager for Python
  ```bash
  curl -sSL https://install.python-poetry.org | python3 -
  ```
- **Docker & Docker Compose**: For running Weaviate locally
  - [Install Docker Desktop](https://www.docker.com/products/docker-desktop/)

### Optional

- **OpenAI API Key**: Required for Azure OpenAI embeddings (can use local models as fallback)
- **Git**: For cloning the repository

:::tip
For development without OpenAI costs, you can use the local SentenceTransformer model (`all-MiniLM-L6-v2`). The service will automatically fall back to this if OpenAI credentials are not provided.
:::

---

## Quick Start: 5-Step Setup

### Step 1: Clone the Repository

```bash
cd /path/to/your/workspace
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/atlas/AtlasMl
```

### Step 2: Set Up Weaviate (Vector Database)

AtlasML requires Weaviate to be running locally. The easiest way is using Docker:

```bash
# Create a docker-compose file for Weaviate
cat > docker-compose.weaviate.yml << 'EOF'
version: '3.8'
services:
  weaviate:
    image: semitechnologies/weaviate:latest
    ports:
      - "8085:8080"
      - "50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'true'
      PERSISTENCE_DATA_PATH: '/var/lib/weaviate'
      DEFAULT_VECTORIZER_MODULE: 'none'
      ENABLE_MODULES: ''
      CLUSTER_HOSTNAME: 'node1'
    volumes:
      - weaviate_data:/var/lib/weaviate

volumes:
  weaviate_data:
EOF

# Start Weaviate
docker compose -f docker-compose.weaviate.yml up -d
```

Verify Weaviate is running:

```bash
curl http://localhost:8085/v1/.well-known/ready
# Should return: {"status":"ok"}
```

:::note
The Weaviate port is mapped to `8085` to avoid conflicts with other services.
:::

### Step 3: Create Environment File

Create a `.env` file in the `/atlas/AtlasMl/` directory:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Required: OpenAI API (or leave empty to use local model)
OPENAI_API_KEY=your-azure-openai-key
OPENAI_API_URL=https://your-resource.openai.azure.com

# Required: API Authentication
ATLAS_API_KEYS=["test-key-123","another-key-456"]

# Required: Weaviate Connection
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085
WEAVIATE_GRPC_PORT=50051

# Optional: Sentry (for production error tracking)
SENTRY_DSN=

# Environment
ENV=development
```

:::warning Important
- `ATLAS_API_KEYS` must be a JSON array: `["key1","key2"]`
- Never commit your `.env` file to git (already in `.gitignore`)
- Use different API keys for development vs production
:::

### Step 4: Install Dependencies

```bash
# Install dependencies with Poetry
poetry install

# Activate the virtual environment
poetry shell
```

This will install all required packages including:
- FastAPI, Uvicorn
- Weaviate client
- Sentence Transformers
- scikit-learn, NumPy, SciPy
- OpenAI SDK

### Step 5: Run the Application

```bash
# Run with auto-reload (development mode)
poetry run uvicorn atlasml.app:app --reload --host 0.0.0.0 --port 8000
```

You should see output like:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using WatchFiles
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
🚀 Starting AtlasML API...
🔌 Weaviate client status: Connected
✅ Weaviate collections initialized
INFO:     Application startup complete.
```

:::tip Success!
Your AtlasML service is now running at **http://localhost:8000**
:::

---

## Verify Installation

### 1. Check Health Endpoint

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:
```json
[]
```

### 2. View API Documentation

Open your browser to:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

These provide interactive API documentation where you can test endpoints directly.

### 3. Make Your First API Request

Test the competency suggestion endpoint:

```bash
curl -X POST "http://localhost:8000/api/v1/competency/suggest" \
  -H "Content-Type: application/json" \
  -H "Authorization: test-key-123" \
  -d '{
    "description": "Understanding of object-oriented programming concepts",
    "course_id": 1
  }'
```

:::note
Replace `test-key-123` with one of your API keys from `.env`.
:::

Expected response (if no competencies exist yet):
```json
{
  "competencies": []
}
```

---

## Common Setup Issues

### Issue: Weaviate Connection Failed

**Symptom:**
```
WeaviateConnectionError: Could not connect to Weaviate
```

**Solutions:**
1. Check if Weaviate is running:
   ```bash
   docker ps | grep weaviate
   ```
2. Verify the port in `.env` matches your Docker setup (default: 8085)
3. Check Weaviate logs:
   ```bash
   docker logs $(docker ps -q --filter ancestor=semitechnologies/weaviate:latest)
   ```

### Issue: Poetry Command Not Found

**Symptom:**
```
bash: poetry: command not found
```

**Solution:**
```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add to PATH (add to your ~/.bashrc or ~/.zshrc)
export PATH="$HOME/.local/bin:$PATH"
```

### Issue: Import Errors

**Symptom:**
```
ModuleNotFoundError: No module named 'atlasml'
```

**Solutions:**
1. Activate Poetry shell:
   ```bash
   poetry shell
   ```
2. Reinstall dependencies:
   ```bash
   poetry install
   ```
3. Verify Python version:
   ```bash
   python --version  # Should be 3.13+
   ```

### Issue: Port 8000 Already in Use

**Symptom:**
```
ERROR: [Errno 48] Address already in use
```

**Solutions:**
1. Use a different port:
   ```bash
   poetry run uvicorn atlasml.app:app --reload --port 8001
   ```
2. Kill the process using port 8000:
   ```bash
   lsof -ti:8000 | xargs kill
   ```

---

## Project Structure

Understanding the AtlasML directory structure:

```
atlas/AtlasMl/
├── atlasml/                    # Main application package
│   ├── app.py                  # FastAPI application entry point
│   ├── config.py               # Configuration management
│   ├── dependencies.py         # Auth dependencies
│   ├── clients/
│   │   └── weaviate.py         # Weaviate client wrapper
│   ├── routers/
│   │   ├── health.py           # Health check endpoint
│   │   └── competency.py       # Competency endpoints
│   ├── models/
│   │   └── competency.py       # Pydantic models
│   ├── ml/
│   │   ├── embeddings.py       # Embedding generation
│   │   ├── clustering.py       # Clustering algorithms
│   │   ├── pipeline_workflows.py  # ML workflow orchestration
│   │   └── ...                 # Other ML modules
│   └── common/
│       └── exceptions.py       # Custom exceptions
├── tests/                      # Test suite
│   ├── conftest.py             # Test fixtures
│   ├── routers/                # Router tests
│   └── ...                     # Unit & integration tests
├── pyproject.toml              # Poetry dependencies
├── Dockerfile                  # Docker image definition
├── .env.example                # Environment variable template
└── README.md                   # Basic readme
```

---

## Next Steps

Now that you have AtlasML running locally, explore these topics:

### For Understanding the System
- 📐 **[Architecture](./architecture.md)**: Learn how AtlasML components work together
- 📦 **[Modules](./modules.md)**: Detailed reference for each code module
- 🔌 **[Weaviate Integration](./weaviate.md)**: Understand the vector database

### For Using the API
- 🌐 **[REST API Framework](./rest-api.md)**: Learn about FastAPI patterns
- 📋 **[API Endpoints](./endpoints.md)**: Detailed endpoint documentation
- 🔒 **[Middleware](./middleware.md)**: Request/response processing

### For Development
- 🛠️ **[Development Workflow](./development-workflow.md)**: Contributing to AtlasML
- 🧪 **[Testing Guide](./testing.md)**: Writing and running tests
- 🐳 **[Docker & Deployment](./docker-deployment.md)**: Deploying AtlasML

### For Debugging
- 🔧 **[Troubleshooting](./troubleshooting.md)**: Common issues and solutions

---

## Additional Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Weaviate Documentation**: https://weaviate.io/developers/weaviate
- **Poetry Documentation**: https://python-poetry.org/docs/
- **OpenAI API**: https://platform.openai.com/docs/

:::tip Need Help?
If you encounter issues not covered here, check the [Troubleshooting Guide](./troubleshooting.md) or ask in the team chat.
:::
