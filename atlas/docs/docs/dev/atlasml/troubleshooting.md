---
title: "Troubleshooting"
description: "Common issues and solutions for AtlasML"
sidebar_position: 12
---

# Troubleshooting

This guide covers common issues you might encounter when working with AtlasML and how to resolve them.

---

## Connection Issues

### Weaviate Connection Failed

**Symptom**:
```
ERROR: WeaviateConnectionError: Could not connect to Weaviate at localhost:8085
```

**Causes**:
1. Weaviate is not running
2. Wrong host/port in configuration
3. Network issues

**Solutions**:

#### 1. Check if Weaviate is Running

```bash
# Check with curl
curl http://localhost:8085/v1/.well-known/ready
# Should return: {"status":"ok"}

# Check Docker container
docker ps | grep weaviate

# Check container logs
docker logs $(docker ps -q --filter ancestor=semitechnologies/weaviate:latest)
```

#### 2. Verify Configuration

Check `.env` file:
```bash
cat .env | grep WEAVIATE
```

Should show:
```
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085
WEAVIATE_GRPC_PORT=50051
```

#### 3. Start Weaviate

```bash
# Using docker-compose
docker compose -f docker-compose.weaviate.yml up -d

# Or pull and run manually
docker run -d \
  -p 8085:8080 \
  -p 50051:50051 \
  semitechnologies/weaviate:latest
```

#### 4. Check Firewall

```bash
# macOS
sudo lsof -i :8085

# Linux
sudo netstat -tulpn | grep 8085
```

---

### OpenAI API Connection Failed

**Symptom**:
```
ERROR: OpenAI API Error: Authentication failed
```

**Solutions**:

#### 1. Check API Key

```bash
echo $OPENAI_API_KEY
# Should show your key
```

#### 2. Test API Directly

```bash
curl https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT/embeddings?api-version=2023-05-15 \
  -H "api-key: YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"test"}'
```

#### 3. Use Local Model Fallback

```python
# Use local SentenceTransformer instead
from atlasml.ml.embeddings import EmbeddingGenerator

generator = EmbeddingGenerator()
embedding = generator.generate_embeddings("text")  # Local model
```

---

## Installation Issues

### Poetry Command Not Found

**Symptom**:
```bash
$ poetry install
bash: poetry: command not found
```

**Solution**:

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add to PATH (add to ~/.bashrc or ~/.zshrc)
export PATH="$HOME/.local/bin:$PATH"

# Reload shell
source ~/.bashrc  # or source ~/.zshrc
```

---

### Python Version Mismatch

**Symptom**:
```
ERROR: Python 3.13 or higher required, found 3.11
```

**Solution**:

```bash
# Check current version
python --version

# Install Python 3.13 (macOS with Homebrew)
brew install python@3.13

# Install Python 3.13 (Ubuntu)
sudo apt update
sudo apt install python3.13

# Use pyenv for version management
pyenv install 3.13.0
pyenv local 3.13.0
```

---

### Module Not Found Errors

**Symptom**:
```
ModuleNotFoundError: No module named 'atlasml'
```

**Solutions**:

#### 1. Activate Poetry Shell

```bash
poetry shell
```

#### 2. Reinstall Dependencies

```bash
poetry install
```

#### 3. Check Python Path

```bash
poetry run python -c "import sys; print('\n'.join(sys.path))"
```

Should include `/path/to/AtlasMl/.venv/lib/python3.13/site-packages`

---

## Runtime Errors

### Validation Errors (422)

**Symptom**:
```json
{
  "detail": [
    {
      "loc": ["body", "course_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Cause**: Request body doesn't match expected schema

**Solution**:

Check the endpoint documentation:
```bash
# View OpenAPI docs
open http://localhost:8000/docs
```

Fix your request:
```python
# ❌ Bad - Missing course_id
{
  "description": "Python programming"
}

# ✅ Good - All required fields
{
  "description": "Python programming",
  "course_id": 1
}
```

---

### Authentication Errors (401)

**Symptom**:
```json
{
  "detail": "Invalid API key"
}
```

**Solutions**:

#### 1. Check API Key in Request

```bash
# Include Authorization header
curl -H "Authorization: your-api-key" http://localhost:8000/api/v1/competency/suggest
```

#### 2. Verify Configured Keys

```bash
# Check .env file
cat .env | grep ATLAS_API_KEYS
# Should show: ATLAS_API_KEYS=["key1","key2"]
```

#### 3. Ensure Correct Format

```bash
# ❌ Bad - Missing quotes or brackets
ATLAS_API_KEYS=key1,key2

# ✅ Good - JSON array format
ATLAS_API_KEYS=["key1","key2"]
```

---

### Internal Server Errors (500)

**Symptom**:
```json
{
  "detail": "Internal server error"
}
```

**Solutions**:

#### 1. Check Logs

```bash
# If running with uvicorn
# Logs appear in terminal

# If running with Docker
docker logs atlasml
```

#### 2. Enable Debug Mode

```python
# In app.py, temporarily add:
app = FastAPI(debug=True)
```

#### 3. Check Sentry (Production)

If `SENTRY_DSN` is configured, check Sentry dashboard for error details.

---

## Performance Issues

### Slow Response Times

**Symptom**: Requests take >5 seconds

**Diagnosis**:

```bash
# Check response time
time curl -X POST http://localhost:8000/api/v1/competency/suggest \
  -H "Authorization: test" \
  -H "Content-Type: application/json" \
  -d '{"description":"test","course_id":1}'
```

**Causes & Solutions**:

#### 1. OpenAI API Latency

```bash
# Benchmark OpenAI
time curl https://YOUR-RESOURCE.openai.azure.com/...
```

**Solution**: Use local embedding model for development:
```python
embedding = generator.generate_embeddings(text)  # Local, ~10-50ms
```

#### 2. Large Weaviate Collection

**Solution**: Add property filters to reduce search space:
```python
# ✅ Filter by course_id
results = client.get_embeddings_by_property(
    collection_name="Competency",
    property_name="course_id",
    property_value=1
)
```

#### 3. Inefficient Similarity Computation

**Solution**: Use Weaviate's built-in vector search instead of computing in Python.

---

### High Memory Usage

**Symptom**:
```
MemoryError: Unable to allocate array
```

**Solutions**:

#### 1. Limit Result Size

```python
# Limit number of results
results = get_all_embeddings("Competency")[:100]  # First 100 only
```

#### 2. Process in Batches

```python
# Instead of loading all at once
all_data = get_all_embeddings("Competency")  # ❌ Loads everything

# Process in chunks
offset = 0
limit = 100
while True:
    chunk = get_embeddings(offset=offset, limit=limit)
    if not chunk:
        break
    process(chunk)
    offset += limit
```

#### 3. Increase Container Memory

```yaml
# docker-compose.yml
services:
  atlasml:
    deploy:
      resources:
        limits:
          memory: 2G
```

---

## Development Issues

### Tests Failing

**Symptom**:
```
FAILED tests/test_competency.py::test_suggest - AssertionError
```

**Solutions**:

#### 1. Run Single Test

```bash
poetry run pytest tests/test_competency.py::test_suggest -v -s
```

#### 2. Check Test Output

```bash
# Run with print statements visible
poetry run pytest tests/test_competency.py -v -s
```

#### 3. Update Test Data

```python
# Ensure test data is current
@pytest.fixture
def sample_data():
    return create_test_data()  # Fresh data each time
```

---

### Code Linting Errors

**Symptom**:
```
atlasml/app.py:45:1: F401 'os' imported but unused
```

**Solutions**:

#### 1. Auto-fix with Ruff

```bash
poetry run ruff check . --fix
```

#### 2. Format with Black

```bash
poetry run black .
```

#### 3. Disable Specific Rules

```python
# For specific lines
import os  # noqa: F401

# For entire file
# ruff: noqa
```

---

### Git Conflicts

**Symptom**:
```
CONFLICT (content): Merge conflict in atlasml/app.py
```

**Solutions**:

#### 1. View Conflicts

```bash
git status
git diff
```

#### 2. Resolve Manually

Edit file and look for:
```python
<<<<<<< HEAD
your changes
=======
their changes
>>>>>>> branch-name
```

Choose or merge changes, then:
```bash
git add atlasml/app.py
git commit -m "Resolve merge conflict"
```

#### 3. Use Merge Tool

```bash
git mergetool
```

---

## Docker Issues

### Container Won't Start

**Symptom**:
```bash
docker ps
# atlasml is not listed
```

**Solutions**:

#### 1. Check Logs

```bash
docker logs atlasml
```

#### 2. Check Environment Variables

```bash
docker exec atlasml env | grep WEAVIATE
```

#### 3. Inspect Container

```bash
docker inspect atlasml
```

#### 4. Test Health Endpoint

```bash
docker exec atlasml curl http://localhost:8000/api/v1/health
```

---

### Port Already in Use

**Symptom**:
```
ERROR: bind: address already in use: 0.0.0.0:8000
```

**Solutions**:

#### 1. Find Process Using Port

```bash
# macOS
lsof -ti:8000

# Linux
sudo netstat -tulpn | grep :8000
```

#### 2. Kill Process

```bash
# macOS
lsof -ti:8000 | xargs kill

# Linux
sudo kill $(sudo lsof -t -i:8000)
```

#### 3. Use Different Port

```bash
docker run -p 8001:8000 atlasml:latest
```

---

### Image Build Fails

**Symptom**:
```
ERROR: failed to solve: process "/bin/sh -c poetry install" did not complete
```

**Solutions**:

#### 1. Clear Build Cache

```bash
docker builder prune
```

#### 2. Rebuild Without Cache

```bash
docker build --no-cache -t atlasml:latest .
```

#### 3. Check Dockerfile

Ensure `pyproject.toml` and `poetry.lock` are copied:
```dockerfile
COPY pyproject.toml poetry.lock README.md ./
```

---

## Database Issues

### Weaviate Collection Not Found

**Symptom**:
```
ERROR: Collection 'Competency' does not exist
```

**Solutions**:

#### 1. Restart Application

Collections are created automatically on startup:
```bash
poetry run uvicorn atlasml.app:app --reload
```

#### 2. Manually Create Collection

```python
from atlasml.clients.weaviate import get_weaviate_client

client = get_weaviate_client()
client.recreate_collection("Competency")
```

#### 3. Check Weaviate Schema

```bash
curl http://localhost:8085/v1/schema
```

---

### Data Not Found

**Symptom**:
```python
results = client.get_embeddings_by_property("Competency", "course_id", 1)
# returns: []
```

**Solutions**:

#### 1. Verify Data Exists

```python
all_comps = client.get_all_embeddings("Competency")
print(f"Total competencies: {len(all_comps)}")
```

#### 2. Check Property Name

```python
# Ensure exact match
results = client.get_embeddings_by_property(
    collection_name="Competency",
    property_name="course_id",  # Exact name from schema
    property_value=1
)
```

#### 3. Inspect Sample Object

```python
all_comps = client.get_all_embeddings("Competency")
if all_comps:
    print(all_comps[0]["properties"])
    # Check actual property names
```

---

## Debugging Tips

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

### Add Breakpoints

```python
import pdb; pdb.set_trace()
```

### Use VS Code Debugger

See [Development Workflow](./development-workflow.md#using-vs-code-debugger)

### Check Environment

```bash
# Python version
python --version

# Poetry version
poetry --version

# Installed packages
poetry show

# Environment variables
printenv | grep -E "(WEAVIATE|OPENAI|ATLAS)"
```

### Test Individual Components

```python
# Test embedding generation
from atlasml.ml.embeddings import EmbeddingGenerator
generator = EmbeddingGenerator()
result = generator.generate_embeddings("test")
print(f"Embedding length: {len(result)}")

# Test Weaviate connection
from atlasml.clients.weaviate import get_weaviate_client
client = get_weaviate_client()
print(f"Weaviate alive: {client.is_alive()}")
```

---

## Getting Help

### Check Logs

```bash
# Application logs
tail -f logs/atlasml.log

# Docker logs
docker logs -f atlasml

# System logs (Linux)
journalctl -u atlasml -f
```

### Reproduce in Minimal Example

```python
# Isolate the issue
from atlasml.ml.embeddings import EmbeddingGenerator

generator = EmbeddingGenerator()
try:
    result = generator.generate_embeddings_openai("test")
    print("Success:", len(result))
except Exception as e:
    print("Error:", e)
```

### Report Issues

When reporting bugs, include:
1. **Description**: What were you trying to do?
2. **Steps to Reproduce**: How can someone else reproduce it?
3. **Expected Behavior**: What should happen?
4. **Actual Behavior**: What actually happened?
5. **Environment**:
   - Python version: `python --version`
   - AtlasML version: `git rev-parse HEAD`
   - OS: `uname -a`
6. **Logs**: Relevant error messages

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `WeaviateConnectionError` | Weaviate not running | Start Weaviate with Docker |
| `ModuleNotFoundError` | Dependencies not installed | Run `poetry install` |
| `401 Unauthorized` | Missing/invalid API key | Check `Authorization` header |
| `422 Unprocessable Entity` | Invalid request body | Check request schema |
| `500 Internal Server Error` | Server-side error | Check logs for details |
| `OpenAIError` | OpenAI API issue | Check API key and quota |
| `ImportError` | Wrong Python version | Use Python 3.13+ |
| `PermissionError` | File permissions | Check file ownership |

---

## Next Steps

- **[Getting Started](./index.md)**: Review setup steps
- **[Architecture](./architecture.md)**: Understand the system
- **[Development Workflow](./development-workflow.md)**: Contributing guide
- **[Testing](./testing.md)**: Write tests to catch issues early

---

## Resources

- **AtlasML GitHub**: https://github.com/ls1intum/edutelligence
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Weaviate Troubleshooting**: https://weaviate.io/developers/weaviate/installation/troubleshooting
- **Poetry Documentation**: https://python-poetry.org/docs/
