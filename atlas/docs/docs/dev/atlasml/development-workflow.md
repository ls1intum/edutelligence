---
title: "Development Workflow"
description: "Guide to developing and contributing to AtlasML"
sidebar_position: 10
---

# Development Workflow

This guide covers the complete development workflow for contributing to AtlasML, from setting up your environment to submitting changes.

---

## Setting Up Development Environment

### 1. Clone the Repository

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/atlas/AtlasMl
```

### 2. Install Dependencies

```bash
# Install with Poetry
poetry install

# Activate virtual environment
poetry shell
```

### 3. Set Up Pre-commit Hooks (Optional)

```bash
# Install pre-commit
pip install pre-commit

# Set up hooks
pre-commit install
```

### 4. Configure IDE

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

## Adding a New Feature

### Step 1: Create a Branch

```bash
git checkout -b feature/my-new-feature
```

### Step 2: Implement the Feature

#### Adding a New Endpoint

**1. Define Pydantic Models** (`atlasml/models/competency.py`):

```python
class MyFeatureRequest(BaseModel):
    input_text: str
    course_id: int

class MyFeatureResponse(BaseModel):
    results: list[str]
```

**2. Create Router Function** (`atlasml/routers/competency.py`):

```python
@router.post("/my-feature", dependencies=[Depends(TokenValidator)])
async def my_feature_endpoint(
    request: MyFeatureRequest
) -> MyFeatureResponse:
    """
    Process the request and return results.

    Args:
        request: Input request with text and course ID

    Returns:
        MyFeatureResponse with processed results
    """
    # Implementation
    results = process_feature(request.input_text, request.course_id)
    return MyFeatureResponse(results=results)
```

**3. Implement Business Logic** (`atlasml/ml/my_feature.py`):

```python
def process_feature(text: str, course_id: int) -> list[str]:
    # Your implementation
    return ["result1", "result2"]
```

**4. Add Tests** (`tests/test_my_feature.py`):

```python
def test_my_feature():
    result = process_feature("test input", 1)
    assert len(result) > 0
```

#### Adding a New ML Pipeline

**1. Create Pipeline Function** (`atlasml/ml/my_pipeline.py`):

```python
def my_ml_pipeline(input_data):
    # 1. Generate embeddings
    generator = EmbeddingGenerator()
    embedding = generator.generate_embeddings_openai(input_data)

    # 2. Query Weaviate
    client = get_weaviate_client()
    results = client.search(...)

    # 3. Process results
    processed = process_results(results)

    return processed
```

**2. Add to PipelineWorkflows** (`atlasml/ml/pipeline_workflows.py`):

```python
class PipelineWorkflows:
    def execute_my_pipeline(self, input_data):
        return my_ml_pipeline(input_data)
```

**3. Use in Router**:

```python
@router.post("/my-pipeline")
async def run_my_pipeline(request: MyRequest):
    pipeline = PipelineWorkflows()
    result = pipeline.execute_my_pipeline(request.data)
    return MyResponse(result=result)
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

### Writing Tests

**Unit Test Example** (`tests/test_my_feature.py`):

```python
import pytest
from atlasml.ml.my_feature import process_feature

def test_process_feature_valid_input():
    result = process_feature("test", 1)
    assert isinstance(result, list)
    assert len(result) > 0

def test_process_feature_empty_input():
    with pytest.raises(ValueError):
        process_feature("", 1)
```

**Integration Test Example** (`tests/routers/test_my_endpoint.py`):

```python
from fastapi.testclient import TestClient
from atlasml.app import app

client = TestClient(app)

def test_my_endpoint_success():
    response = client.post(
        "/api/v1/competency/my-feature",
        headers={"Authorization": "test"},
        json={"input_text": "test", "course_id": 1}
    )
    assert response.status_code == 200
    assert "results" in response.json()

def test_my_endpoint_auth_required():
    response = client.post(
        "/api/v1/competency/my-feature",
        json={"input_text": "test", "course_id": 1}
    )
    assert response.status_code == 401
```

See **[Testing Guide](./testing.md)** for more details.

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

## Committing Changes

### 1. Check Status

```bash
git status
git diff
```

### 2. Stage Changes

```bash
# Stage specific files
git add atlasml/routers/competency.py
git add tests/test_my_feature.py

# Stage all changes
git add .
```

### 3. Run Linters

```bash
poetry run black .
poetry run ruff check . --fix
```

### 4. Run Tests

```bash
poetry run pytest -v
```

### 5. Commit

```bash
git commit -m "Add my new feature

- Implemented feature X
- Added tests for feature X
- Updated documentation"
```

**Commit Message Format**:
- First line: Short summary (50 chars max)
- Blank line
- Body: Detailed description (bullet points)

### 6. Push

```bash
git push origin feature/my-new-feature
```

---

## Creating a Pull Request

### 1. Push Your Branch

```bash
git push origin feature/my-new-feature
```

### 2. Open PR on GitHub

1. Go to https://github.com/ls1intum/edutelligence
2. Click "Compare & pull request"
3. Fill in PR template:

```markdown
## What?
Brief description of changes

## Why?
Motivation for changes

## How?
Technical implementation details

## Testing
- [ ] Tests added/updated
- [ ] All tests passing
- [ ] Manual testing completed

## Screenshots
(if applicable)
```

### 3. Request Review

Tag relevant reviewers.

### 4. Address Feedback

```bash
# Make changes based on feedback
git add .
git commit -m "Address review feedback"
git push
```

---

## Code Review Checklist

### For Reviewers

- [ ] Code follows style guide
- [ ] Tests added for new functionality
- [ ] All tests passing
- [ ] No hardcoded secrets or credentials
- [ ] Error handling implemented
- [ ] Documentation updated
- [ ] Performance considerations addressed
- [ ] Security implications reviewed

### For Authors

Before requesting review:

- [ ] Code formatted with Black
- [ ] Code linted with Ruff (no errors)
- [ ] All tests passing
- [ ] New tests added
- [ ] Documentation updated
- [ ] Manual testing completed
- [ ] Branch up to date with main

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

# 5. Commit
git add atlasml/routers/competency.py
git commit -m "Update competency endpoint"
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

# 5. Commit with issue reference
git commit -m "Fix #123: Description of bug fix"
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

# 5. Commit
git commit -m "Refactor: Improve code organization"
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

- **[Testing Guide](./testing.md)**: Write comprehensive tests
- **[Architecture](./architecture.md)**: Understand the system
- **[Modules](./modules.md)**: Navigate the codebase
- **[Troubleshooting](./troubleshooting.md)**: Debug issues

---

## Resources

- **Poetry Documentation**: https://python-poetry.org/docs/
- **FastAPI Testing**: https://fastapi.tiangolo.com/tutorial/testing/
- **Pytest Documentation**: https://docs.pytest.org/
- **Black Code Style**: https://black.readthedocs.io/
- **Ruff Linter**: https://docs.astral.sh/ruff/
