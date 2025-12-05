---
title: "Setup Guide"
description: "Guide to setting up your local development environment for AtlasML"
sidebar_position: 3
---

# Setup Guide

This guide covers setting up your local development environment for contributing to AtlasML.

---

## Setting Up Development Environment

### 1. Clone the Repository

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/atlas/AtlasMl
```

### 2. Start Local Infrastructure

AtlasML requires Weaviate (vector database) and Multi2vec-CLIP (for embeddings). Start them using Docker Compose:

```bash
# From the atlas directory (parent of AtlasMl)
cd ..
docker compose -f docker-compose.dev.yml up -d
```

**This starts:**
- Weaviate on `http://localhost:8085` (no authentication required)
- Multi2vec-CLIP on `http://localhost:8081` (for embeddings)

**Verify services are running:**
```bash
# Check Weaviate
curl http://localhost:8085/v1/.well-known/ready
# Should return: {"status":"ok"}

# Check Multi2vec-CLIP
curl http://localhost:8081/.well-known/ready
# Should return: status 200

# Or check Docker
docker ps | grep -E "weaviate|multi2vec"
```

**To stop infrastructure later:**
```bash
docker compose -f docker-compose.dev.yml down
```

**To reset Weaviate data:**
```bash
docker compose -f docker-compose.dev.yml down -v  # Remove volumes
docker compose -f docker-compose.dev.yml up -d    # Start fresh
```

### 3. Install Dependencies

```bash
# Return to AtlasMl directory
cd AtlasMl

# Install with Poetry
poetry install

# Activate virtual environment
poetry shell
```

### 4. Configure Environment Variables

Create a `.env` file based on the example:

```bash
cp .env.example .env
```

**Edit `.env` with your credentials:**
```bash
# AtlasML Authentication (for API endpoints)
ATLAS_API_KEYS=dev-test-key

# Local Weaviate (no authentication needed for dev)
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085

# Azure OpenAI (required for embeddings - contact your team for credentials)
OPENAI_API_KEY=your-azure-openai-key
OPENAI_API_URL=https://your-instance.openai.azure.com

# Optional
SENTRY_DSN=
ENV=development
```

:::tip
You need valid Azure OpenAI credentials for the embedding functionality to work. Contact your team lead to get access to the development Azure OpenAI instance.
:::

### 5. Set Up Pre-commit Hooks (Optional)

```bash
# Install pre-commit
pip install pre-commit

# Set up hooks
pre-commit install
```

### 6. Configure IDE

#### VS Code

Create `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.ruffEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.codeActionsOnSave": {
      "source.organizeImports": true
    }
  }
}
```

#### PyCharm

1. Go to Settings → Project → Python Interpreter
2. Select Poetry environment
3. Enable "Black" formatter
4. Enable "Ruff" linter

---

## Code Style & Linting

### Ruff (Linting)

**Configuration**: `pyproject.toml`

```bash
# Check code
poetry run ruff check .

# Fix auto-fixable issues
poetry run ruff check . --fix

# Check specific file
poetry run ruff check atlasml/routers/competency.py
```

**Rules Enabled**:
- `E`: PyCodeStyle errors
- `F`: Pyflakes
- `B`: Flake8-bugbear
- `I`: Isort (import sorting)
- `N`: Naming conventions
- `UP`: Pyupgrade
- `PL`: Pylint
- `RUF`: Ruff-specific rules

### Black (Formatting)

```bash
# Format all code
poetry run black .

# Check without modifying
poetry run black . --check

# Format specific file
poetry run black atlasml/app.py
```

**Configuration**:
```toml
[tool.black]
line-length = 88
target-version = ["py312"]
```

### Running Both

```bash
# Format then lint
poetry run black . && poetry run ruff check . --fix
```

---

## Running the Application

### Development Mode (with Auto-reload)

```bash
poetry run uvicorn atlasml.app:app --reload --host 0.0.0.0 --port 8000
```

**Flags**:
- `--reload`: Restart on code changes
- `--host 0.0.0.0`: Listen on all interfaces
- `--port 8000`: Port to run on

### Production Mode

```bash
poetry run uvicorn atlasml.app:app --host 0.0.0.0 --port 8000
```

### With Environment Variables

```bash
WEAVIATE_HOST=localhost WEAVIATE_PORT=8085 poetry run uvicorn atlasml.app:app --reload
```

---

## Testing Your Changes

### Running Tests

```bash
# Run all tests
poetry run pytest -v

# Run specific test file
poetry run pytest tests/test_competency.py -v

# Run specific test function
poetry run pytest tests/test_competency.py::test_suggest_competencies -v

# Run with coverage
poetry run pytest --cov=atlasml --cov-report=html
```

See **[Test Guide](./testing.md)** for detailed testing information.

---

## Debugging

### Using Print Statements

```python
@router.post("/suggest")
async def suggest_competencies(request: SuggestCompetencyRequest):
    print(f"DEBUG: Received request: {request}")

    results = generate_suggestions(request)
    print(f"DEBUG: Generated {len(results)} results")

    return results
```

### Using Python Debugger

```python
import pdb

@router.post("/suggest")
async def suggest_competencies(request: SuggestCompetencyRequest):
    pdb.set_trace()  # Execution stops here
    results = generate_suggestions(request)
    return results
```

### Using VS Code Debugger

**1. Create `.vscode/launch.json`**:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "atlasml.app:app",
        "--reload"
      ],
      "jinja": true,
      "justMyCode": false
    }
  ]
}
```

**2. Set Breakpoints**: Click left gutter in editor

**3. Start Debugging**: Press F5

### Logging

```python
import logging

logger = logging.getLogger(__name__)

@router.post("/suggest")
async def suggest_competencies(request: SuggestCompetencyRequest):
    logger.info(f"Processing suggestion request for course {request.course_id}")
    logger.debug(f"Description: {request.description}")

    try:
        results = generate_suggestions(request)
        logger.info(f"Generated {len(results)} suggestions")
        return results
    except Exception as e:
        logger.error(f"Error generating suggestions: {e}", exc_info=True)
        raise
```

---

## Working with Dependencies

### Adding a Dependency

```bash
# Add to main dependencies
poetry add package-name

# Add to dev dependencies
poetry add --group dev package-name

# Add to test dependencies
poetry add --group test package-name
```

**Example**:
```bash
poetry add requests
poetry add --group dev ipython
poetry add --group test pytest-mock
```

### Updating Dependencies

```bash
# Update all
poetry update

# Update specific package
poetry update fastapi

# See outdated packages
poetry show --outdated
```

### Removing a Dependency

```bash
poetry remove package-name
```

---

## Working with Migrations

### Adding a New Weaviate Collection

**1. Define Schema** (`atlasml/clients/weaviate.py`):

```python
MY_COLLECTION_SCHEMA = {
    "class": "MyCollection",
    "description": "My new collection",
    "vectorizer": "none",
    "properties": [
        {
            "name": "my_property",
            "dataType": ["text"],
            "description": "My property"
        }
    ]
}

COLLECTION_SCHEMAS = {
    ...
    CollectionNames.MY_COLLECTION.value: MY_COLLECTION_SCHEMA
}
```

**2. Add to CollectionNames**:

```python
class CollectionNames(str, Enum):
    EXERCISE = "Exercise"
    COMPETENCY = "Competency"
    SEMANTIC_CLUSTER = "SemanticCluster"
    MY_COLLECTION = "MyCollection"  # New!
```

**3. Collection Created Automatically**: On next startup

---

## Common Development Tasks

### Task 1: Update an Endpoint

```bash
# 1. Find endpoint
vim atlasml/routers/competency.py

# 2. Make changes
# 3. Run tests
poetry run pytest tests/routers/test_competency.py -v

# 4. Test manually
curl -X POST http://localhost:8000/api/v1/competency/suggest \
  -H "Authorization: test" \
  -d '{"description":"test","course_id":1}'

# 5. Commit (see Development Process for git workflow)
```

### Task 2: Fix a Bug

```bash
# 1. Write a failing test
vim tests/test_bug.py

# 2. Run test (should fail)
poetry run pytest tests/test_bug.py -v

# 3. Fix the bug
vim atlasml/...

# 4. Run test (should pass)
poetry run pytest tests/test_bug.py -v

# 5. Commit (see Development Process for git workflow)
```

### Task 3: Refactor Code

```bash
# 1. Ensure all tests pass
poetry run pytest -v

# 2. Refactor code
# 3. Run tests again (should still pass)
poetry run pytest -v

# 4. Check coverage
poetry run pytest --cov=atlasml

# 5. Commit (see Development Process for git workflow)
```

---

## Best Practices

### 1. Write Tests First (TDD)

```python
# ✅ Good - Test first
def test_new_feature():
    result = new_feature("input")
    assert result == "expected"

# Then implement
def new_feature(input):
    return "expected"
```

### 2. Keep Functions Small

```python
# ✅ Good - Small, focused functions
def get_competencies(course_id):
    return fetch_from_db(course_id)

def filter_competencies(competencies, criteria):
    return [c for c in competencies if matches(c, criteria)]

# ❌ Bad - Too many responsibilities
def get_and_filter_competencies(course_id, criteria):
    competencies = fetch_from_db(course_id)
    filtered = [c for c in competencies if matches(c, criteria)]
    return filtered
```

### 3. Use Type Hints

```python
# ✅ Good
def process_data(data: list[str]) -> dict[str, int]:
    return {item: len(item) for item in data}

# ❌ Bad
def process_data(data):
    return {item: len(item) for item in data}
```

### 4. Handle Errors Gracefully

```python
# ✅ Good
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}")
    raise HTTPException(500, "Operation failed")

# ❌ Bad
result = risky_operation()  # Might crash
```

### 5. Document Complex Logic

```python
# ✅ Good
def complex_algorithm(data):
    """
    Process data using Smith's algorithm (2019).

    Steps:
    1. Normalize input
    2. Apply transformation matrix
    3. Compute eigenvectors

    Args:
        data: Input matrix (n × m)

    Returns:
        Processed result
    """
    ...
```

---

## Next Steps

- **[Development Process](./development-process/index.md)**: Learn the complete development workflow
- **[Test Guide](./testing.md)**: Write comprehensive tests
- **[System Design](./system-design.md)**: Understand the system architecture
- **[Code Reference](./code-reference/modules.md)**: Navigate the codebase
- **[Troubleshooting](/admin/atlasml-troubleshooting.md)**: Debug issues

---

## Resources

- **Poetry Documentation**: https://python-poetry.org/docs/
- **FastAPI Testing**: https://fastapi.tiangolo.com/tutorial/testing/
- **Pytest Documentation**: https://docs.pytest.org/
- **Black Code Style**: https://black.readthedocs.io/
- **Ruff Linter**: https://docs.astral.sh/ruff/
