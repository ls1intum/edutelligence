---
title: "Test Guide"
description: "Complete guide to writing and running tests in AtlasML"
sidebar_position: 4
---

# Test Guide

AtlasML uses **pytest** for testing. This guide covers how to write, run, and organize tests effectively.

---

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures
├── test_config.py              # Config tests
├── test_weaviate.py            # Weaviate client tests
├── test_clustering.py          # Clustering tests
├── test_similarityMeasurement.py  # Similarity tests
├── test_pipelines.py           # Integration tests
├── routers/
│   ├── test_health.py          # Health endpoint tests
│   └── test_competency.py      # Competency endpoint tests
└── ...
```

**Organization**:
- **Root level**: Unit tests for modules
- **routers/**: Integration tests for API endpoints
- **conftest.py**: Shared test fixtures

---

## Running Tests

### All Tests

```bash
poetry run pytest -v
```

**Output**:
```
tests/test_config.py::test_get_settings PASSED
tests/test_weaviate.py::test_connection PASSED
tests/routers/test_health.py::test_health_endpoint PASSED
...
===== 45 passed in 2.50s =====
```

### Specific Test File

```bash
poetry run pytest tests/test_config.py -v
```

### Specific Test Function

```bash
poetry run pytest tests/test_config.py::test_get_settings -v
```

### By Pattern

```bash
# Run all tests with "competency" in the name
poetry run pytest -k competency -v

# Run all tests in routers/
poetry run pytest tests/routers/ -v
```

### With Coverage

```bash
# Run with coverage report
poetry run pytest --cov=atlasml --cov-report=html

# View HTML report
open htmlcov/index.html
```

### Stop on First Failure

```bash
poetry run pytest -x
```

### Run Failed Tests Only

```bash
# Run, then rerun only failures
poetry run pytest --lf
```

---

## Writing Unit Tests

### Basic Test Structure

```python
# tests/test_my_module.py

def test_function_name():
    # Arrange: Set up test data
    input_data = "test"

    # Act: Execute the function
    result = my_function(input_data)

    # Assert: Verify the result
    assert result == "expected"
```

### Example: Testing a Utility Function

**Code** (`atlasml/ml/similarity_measures.py`):
```python
def compute_cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    import math
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude_a = math.sqrt(sum(a**2 for a in vec1))
    magnitude_b = math.sqrt(sum(b**2 for b in vec2))
    return dot_product / (magnitude_a * magnitude_b)
```

**Test** (`tests/test_similarityMeasurement.py`):
```python
from atlasml.ml.similarity_measures import compute_cosine_similarity

def test_cosine_similarity_identical_vectors():
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [1.0, 2.0, 3.0]
    similarity = compute_cosine_similarity(vec1, vec2)
    assert similarity == 1.0

def test_cosine_similarity_orthogonal_vectors():
    vec1 = [1.0, 0.0]
    vec2 = [0.0, 1.0]
    similarity = compute_cosine_similarity(vec1, vec2)
    assert similarity == 0.0

def test_cosine_similarity_opposite_vectors():
    vec1 = [1.0, 2.0]
    vec2 = [-1.0, -2.0]
    similarity = compute_cosine_similarity(vec1, vec2)
    assert similarity == -1.0
```

---

## Writing Integration Tests

### Testing API Endpoints

**File**: `tests/routers/test_health.py`

```python
from fastapi.testclient import TestClient
from atlasml.app import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == []
```

### Testing with Authentication

**File**: `tests/routers/test_competency.py`

```python
from fastapi.testclient import TestClient
from atlasml.app import app

client = TestClient(app)

def test_suggest_competencies_success():
    response = client.post(
        "/api/v1/competency/suggest",
        headers={"Authorization": "test"},
        json={
            "description": "Python programming",
            "course_id": 1
        }
    )
    assert response.status_code == 200
    assert "competencies" in response.json()

def test_suggest_competencies_no_auth():
    response = client.post(
        "/api/v1/competency/suggest",
        json={
            "description": "Python programming",
            "course_id": 1
        }
    )
    assert response.status_code == 401

def test_suggest_competencies_invalid_request():
    response = client.post(
        "/api/v1/competency/suggest",
        headers={"Authorization": "test"},
        json={
            "description": "Python programming"
            # Missing course_id
        }
    )
    assert response.status_code == 422
```

---

## Using Fixtures

### What are Fixtures?

Fixtures provide reusable test setup and teardown.

**File**: `tests/conftest.py`

```python
import pytest
from atlasml.clients.weaviate import WeaviateClient
from atlasml.config import Settings

@pytest.fixture
def test_settings():
    """Provide test settings with defaults."""
    return Settings._get_default_settings()

@pytest.fixture
def weaviate_client(test_settings):
    """Provide a Weaviate client for testing."""
    client = WeaviateClient(test_settings.weaviate)
    yield client
    # Cleanup after test
    client.close()

@pytest.fixture
def test_client():
    """Provide FastAPI test client."""
    from fastapi.testclient import TestClient
    from atlasml.app import app
    return TestClient(app)
```

### Using Fixtures

```python
def test_weaviate_connection(weaviate_client):
    # weaviate_client is automatically provided
    assert weaviate_client.is_alive()

def test_api_endpoint(test_client):
    # test_client is automatically provided
    response = test_client.get("/api/v1/health/")
    assert response.status_code == 200
```

### Fixture Scopes

```python
@pytest.fixture(scope="function")  # Default: runs before each test
def function_fixture():
    return "data"

@pytest.fixture(scope="module")  # Runs once per test file
def module_fixture():
    return "data"

@pytest.fixture(scope="session")  # Runs once per test session
def session_fixture():
    return "data"
```

---

## Mocking

### Mocking External APIs

**Example**: Mock OpenAI API calls

```python
import pytest
from unittest.mock import patch, MagicMock

@patch('atlasml.ml.embeddings.AzureOpenAI')
def test_generate_embeddings_openai(mock_openai):
    # Mock the API response
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_openai.return_value.embeddings.create.return_value = mock_response

    # Test the function
    from atlasml.ml.embeddings import EmbeddingGenerator
    generator = EmbeddingGenerator()
    result = generator.generate_embeddings_openai("test")

    assert len(result) == 3
    assert result == [0.1, 0.2, 0.3]
```

### Mocking Weaviate

```python
@patch('atlasml.clients.weaviate.weaviate.connect_to_local')
def test_weaviate_operation(mock_connect):
    # Mock Weaviate client
    mock_client = MagicMock()
    mock_client.is_live.return_value = True
    mock_connect.return_value = mock_client

    # Test code that uses Weaviate
    from atlasml.clients.weaviate import WeaviateClient
    client = WeaviateClient()

    assert client.is_alive()
```

### pytest-mock Plugin

```bash
poetry add --group test pytest-mock
```

```python
def test_with_mocker(mocker):
    # mocker fixture provided by pytest-mock
    mock_func = mocker.patch('module.function')
    mock_func.return_value = "mocked"

    result = call_function()
    assert result == "mocked"
```

---

## Async Testing

### Testing Async Functions

**File**: `tests/test_async.py`

```python
import pytest

@pytest.mark.asyncio
async def test_async_endpoint():
    from httpx import AsyncClient
    from atlasml.app import app

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/health/")
        assert response.status_code == 200
```

**Configuration**: `pyproject.toml`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Parametrized Tests

### Testing Multiple Inputs

```python
import pytest

@pytest.mark.parametrize("vec1,vec2,expected", [
    ([1, 0], [1, 0], 1.0),      # Identical
    ([1, 0], [0, 1], 0.0),      # Orthogonal
    ([1, 1], [-1, -1], -1.0),   # Opposite
])
def test_cosine_similarity_cases(vec1, vec2, expected):
    from atlasml.ml.similarity_measures import compute_cosine_similarity
    result = compute_cosine_similarity(vec1, vec2)
    assert result == pytest.approx(expected)
```

### Parametrize with IDs

```python
@pytest.mark.parametrize("description,course_id", [
    ("Python programming", 1),
    ("Data structures", 2),
    ("Algorithms", 3),
], ids=["python", "data-structures", "algorithms"])
def test_suggestions(description, course_id):
    # Test with different inputs
    pass
```

---

## Test Coverage

### Running with Coverage

```bash
poetry run pytest --cov=atlasml --cov-report=term-missing
```

**Output**:
```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
atlasml/__init__.py                   0      0   100%
atlasml/app.py                       45      5    89%   78-82
atlasml/config.py                    32      2    94%   45, 67
atlasml/routers/competency.py        68     10    85%   120-130
---------------------------------------------------------------
TOTAL                               456     45    90%
```

### HTML Coverage Report

```bash
poetry run pytest --cov=atlasml --cov-report=html
open htmlcov/index.html
```

### Coverage Requirements

```toml
[tool.pytest.ini_options]
# Fail if coverage < 80%
addopts = "--cov=atlasml --cov-fail-under=80"
```

---

## Testing Best Practices

### 1. Test One Thing Per Test

```python
# ✅ Good - Tests one behavior
def test_save_competency_success():
    result = save_competency(valid_competency)
    assert result.id == valid_competency.id

def test_save_competency_invalid_input():
    with pytest.raises(ValueError):
        save_competency(invalid_competency)

# ❌ Bad - Tests multiple behaviors
def test_save_competency():
    result = save_competency(valid_competency)
    assert result.id == valid_competency.id

    with pytest.raises(ValueError):
        save_competency(invalid_competency)
```

### 2. Use Descriptive Test Names

```python
# ✅ Good
def test_suggest_competencies_returns_empty_list_when_no_matches():
    ...

# ❌ Bad
def test_suggest():
    ...
```

### 3. Arrange-Act-Assert Pattern

```python
def test_compute_similarity():
    # Arrange: Set up test data
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [1.0, 2.0, 3.0]

    # Act: Execute the function
    result = compute_cosine_similarity(vec1, vec2)

    # Assert: Verify the result
    assert result == 1.0
```

### 4. Test Edge Cases

```python
def test_process_empty_list():
    result = process([])
    assert result == []

def test_process_single_item():
    result = process([1])
    assert result == [1]

def test_process_large_list():
    result = process([1] * 10000)
    assert len(result) == 10000
```

### 5. Use Fixtures for Setup

```python
# ✅ Good - Reusable fixture
@pytest.fixture
def sample_competency():
    return Competency(
        id=1,
        title="Test",
        description="Test description",
        course_id=1
    )

def test_save(sample_competency):
    result = save(sample_competency)
    assert result.id == 1

# ❌ Bad - Duplicate setup
def test_save():
    comp = Competency(id=1, title="Test", ...)
    result = save(comp)
    assert result.id == 1
```

### 6. Don't Test Implementation Details

```python
# ✅ Good - Tests behavior
def test_suggest_returns_top_5_results():
    results = suggest("query", course_id=1)
    assert len(results) <= 5

# ❌ Bad - Tests implementation
def test_suggest_uses_cosine_similarity():
    with patch('module.compute_cosine_similarity') as mock:
        suggest("query", course_id=1)
        assert mock.called  # Fragile!
```

---

## Common Testing Patterns

### Pattern 1: Test Error Handling

```python
def test_function_raises_error_on_invalid_input():
    with pytest.raises(ValueError) as exc_info:
        my_function(invalid_input)

    assert "expected error message" in str(exc_info.value)
```

### Pattern 2: Test API Endpoint

```python
def test_endpoint(test_client):
    response = test_client.post(
        "/api/v1/endpoint",
        headers={"Authorization": "test"},
        json={"key": "value"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "expected_key" in data
```

### Pattern 3: Test with Database

```python
@pytest.fixture
def clean_database(weaviate_client):
    # Setup: Clean database
    weaviate_client.delete_all_data_from_collection("Competency")

    yield

    # Teardown: Clean again
    weaviate_client.delete_all_data_from_collection("Competency")

def test_with_database(clean_database, weaviate_client):
    # Test with clean database
    weaviate_client.add_embeddings(...)
    results = weaviate_client.get_all_embeddings(...)
    assert len(results) == 1
```

### Pattern 4: Test Async Code

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result == "expected"
```

---

## Debugging Tests

### Run with Print Statements

```python
def test_debug():
    print("DEBUG: Starting test")
    result = my_function()
    print(f"DEBUG: Result = {result}")
    assert result == expected
```

Run with `-s` to see output:
```bash
poetry run pytest tests/test_file.py::test_debug -v -s
```

### Use `pytest.set_trace()`

```python
def test_debug():
    import pytest
    result = my_function()
    pytest.set_trace()  # Drops into debugger
    assert result == expected
```

### Run Single Test with Debugger

```bash
poetry run pytest tests/test_file.py::test_function --pdb
```

---

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.13'

      - name: Install Poetry
        run: pip install poetry

      - name: Install dependencies
        run: poetry install

      - name: Run tests
        run: poetry run pytest --cov=atlasml --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

---

## Next Steps

- **[Development Process](./development-process/index.md)**: Learn to add features with tests
- **[Modules](./code-reference/modules.md)**: Understand what to test
- **[Troubleshooting](/admin/atlasml-troubleshooting.md)**: Debug test failures
- **[System Design](./system-design.md)**: Understand integration points

---

## Resources

- **Pytest Documentation**: https://docs.pytest.org/
- **FastAPI Testing**: https://fastapi.tiangolo.com/tutorial/testing/
- **pytest-asyncio**: https://pytest-asyncio.readthedocs.io/
- **pytest-cov**: https://pytest-cov.readthedocs.io/
- **unittest.mock**: https://docs.python.org/3/library/unittest.mock.html
