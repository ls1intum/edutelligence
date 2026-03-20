---
title: Testing
---

# Testing

This page covers how to run tests, check code quality, and work with the existing test infrastructure in Iris.

## Running Tests

Iris uses [pytest](https://docs.pytest.org/) for testing. Run the full test suite from the `iris/` directory:

```bash
poetry run pytest
```

To run with verbose output:

```bash
poetry run pytest -v
```

To run a specific test file:

```bash
poetry run pytest tests/test_session_title_generation_pipeline.py -v
```

### Code Coverage

Generate a coverage report:

```bash
poetry run coverage run -m pytest     # Run tests with coverage tracking
poetry run coverage html              # Generate HTML report in htmlcov/
poetry run coverage report            # Print summary to terminal
```

Coverage is configured in `pyproject.toml`:

```toml
[tool.coverage.run]
branch = true
source = ["src"]
dynamic_context = "test_function"

[tool.coverage.report]
show_missing = true
```

## Test Structure

The test directory currently has minimal coverage:

```
tests/
├── __init__.py
├── test_dummy.py                              # Basic smoke test
└── test_session_title_generation_pipeline.py  # Session title pipeline tests
```

:::note
Test coverage is an area for improvement. When adding new features, please add corresponding tests.
:::

## Linting and Code Quality

Iris uses several tools for code quality, configured in `pyproject.toml` and enforced via pre-commit hooks.

### Black (Code Formatter)

[Black](https://black.readthedocs.io/) enforces consistent code formatting:

```bash
poetry run black src/ tests/
```

To check without modifying files:

```bash
poetry run black --check src/ tests/
```

### isort (Import Sorter)

[isort](https://pycqa.github.io/isort/) sorts and organizes imports:

```bash
poetry run isort src/ tests/
```

Configuration in `pyproject.toml`:

```toml
[tool.isort]
profile = "black"
multi_line_output = 3
```

The `profile = "black"` setting ensures isort's output is compatible with Black's formatting.

### Pylint (Static Analysis)

[Pylint](https://pylint.readthedocs.io/) catches bugs, enforces coding standards, and detects code smells:

```bash
poetry run pylint src/iris/
```

### Additional Tools

| Tool               | Purpose                              | Command                               |
| ------------------ | ------------------------------------ | ------------------------------------- |
| **mypy**           | Static type checking                 | `poetry run mypy src/`                |
| **bandit**         | Security linting                     | `poetry run bandit -r src/ -x tests/` |
| **yamllint**       | YAML file linting                    | `poetry run yamllint *.yml`           |
| **autoflake**      | Remove unused imports                | `poetry run autoflake --check src/`   |
| **detect-secrets** | Prevent secrets from being committed | See below                             |

### Detect Secrets

Scan all tracked files for accidentally committed secrets:

```bash
git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline
```

To update the baseline with current (known/accepted) secrets:

```bash
git ls-files -z | xargs -0 detect-secrets scan --baseline .secrets.baseline
```

## Pre-commit Hooks

The pre-commit framework runs all quality checks automatically before each commit. Install hooks from the **monorepo root**:

```bash
cd ..  # from iris/ to edutelligence/
pre-commit install
```

To run all hooks manually on all files:

```bash
pre-commit run --all-files
```

This executes Black, isort, Pylint, detect-secrets, and other configured hooks. Pre-commit configuration is defined in `.pre-commit-config.yaml` at the monorepo root.

## Writing New Tests

When adding tests:

1. Place test files in the `tests/` directory.
2. Name test files with the `test_` prefix (e.g., `test_my_pipeline.py`).
3. Name test functions with the `test_` prefix.
4. Use pytest fixtures for shared setup.

### Example Test

```python
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

def test_session_title_generation():
    """Test that session title generation produces a non-empty result."""
    pipeline = SessionTitleGenerationPipeline()
    result = pipeline(
        current_session_title="",
        recent_messages=["User: How do I use sorting?", "Assistant: Here's how..."],
        user_language="en",
    )
    assert result is not None
```

:::tip
Since Iris relies heavily on external services (LLMs, Weaviate), consider mocking these dependencies in unit tests. Use `unittest.mock.patch` or pytest's `monkeypatch` fixture to replace LLM calls and database operations.
:::
