---
title: Mock vs Real Testing
---

Athena's testing framework employs a dual approach:

> **Mock Tests** for fast, isolated unit testing and **Real Tests** for
> comprehensive integration testing. This section explains the
> differences, use cases, and implementation details of each approach.

# Mock Testing

## Purpose and Benefits

Mock tests provide fast, reliable, and isolated testing by replacing
external dependencies with controlled mock objects. They are ideal for:

- **Unit Testing**: Testing individual functions and methods in
  isolation
- **Fast Feedback**: Quick test execution during development
- **Deterministic Results**: Consistent outcomes regardless of external
  factors
- **CI/CD Integration**: Reliable automated testing without external
  dependencies

## Mock Test Structure

Mock tests are located in `mock/` directories and typically include:

``` text
mock/
├── conftest.py              # Mock fixtures and configuration
├── test_*.py               # Mock test files
└── utils/                  # Mock utilities
    ├── mock_config.py      # Mock configuration objects
    ├── mock_llm.py         # Mock LLM implementations
    ├── mock_openai.py      # Mock OpenAI API responses
    └── mock_env.py         # Mock environment variables
```

## Key Mock Components

### Mock LLM Responses

``` python
class MockLanguageModel:
    def __init__(self):
        self.responses = {
            "feedback_suggestion": "This is a mock feedback response.",
            "grading_analysis": "Mock grading analysis result."
        }

    async def ainvoke(self, prompt):
        # Return predetermined responses based on prompt content
        return self.responses.get("feedback_suggestion", "Default mock response")
```

### Mock Configuration Objects

``` python
class MockApproachConfig:
    def __init__(self):
        self.max_input_tokens = 5000
        self.model = MockModelConfig()
        self.type = "default"
```

### Mock Environment Variables

``` python
@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("API_KEY", "mock_api_key")
```

## Mock Test Example

``` python
import pytest
from unittest.mock import patch
from module_text_llm.default_approach import generate_suggestions
from tests.modules.text.module_text_llm.mock.utils.mock_config import MockApproachConfig

@pytest.mark.asyncio
async def test_feedback_generation_mock(mock_config, mock_llm):
    """Test feedback generation with mocked LLM responses."""

    # Arrange
    exercise = create_mock_exercise()
    submission = create_mock_submission()

    # Act
    feedbacks = await generate_suggestions(
        exercise=exercise,
        submission=submission,
        config=mock_config,
        debug=False,
        is_graded=True,
        learner_profile=None
    )

    # Assert
    assert len(feedbacks) > 0
    assert all(f.title for f in feedbacks)
    assert all(f.description for f in feedbacks)
```

# Real Testing

## Purpose and Benefits

Real tests provide comprehensive integration testing by using actual
APIs and services. They are essential for:

- **Integration Testing**: Testing complete workflows with real
  dependencies
- **API Validation**: Ensuring compatibility with external services
- **Performance Testing**: Measuring actual response times and resource
  usage
- **End-to-End Validation**: Verifying complete system functionality

## Real Test Structure

Real tests are located in `real/` directories and include:

``` text
real/
├── conftest.py              # Real test fixtures and configuration
├── test_*.py               # Real test files
├── data/                   # Real test data
│   └── exercises/          # Exercise JSON files
│       ├── exercise-6715.json
│       ├── exercise-6787.json
│       └── ...
└── test_data/              # Additional test data (modeling module)
    ├── ecommerce_data.py
    └── hospital_data.py
```

## Real Test Configuration

### Azure OpenAI Configuration

``` python
@pytest.fixture
def real_config():
    """Create a real configuration for testing with Azure OpenAI."""
    return DefaultApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",
            get_model=lambda: None,  # Set by the module
        ),
        type="default",
    )
```

### Environment Setup

``` python
@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Setup environment for real tests."""
    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)
```

## Real Test Example

``` python
import pytest
from module_text_llm.default_approach import generate_suggestions
from tests.modules.text.module_text_llm.real.conftest import real_config

@pytest.mark.asyncio
async def test_feedback_generation_real(real_config, playground_loader):
    """Test feedback generation with real LLM API calls."""

    # Load real exercise data
    exercise_data = playground_loader.load_exercise(4)
    exercise = playground_loader.convert_to_athena_exercise(exercise_data)

    # Create test submission
    submission_data = {"id": 401, "text": "MVC test"}
    submission = playground_loader.convert_to_athena_submission(submission_data, exercise.id)

    # Generate feedback with real API
    feedbacks = await generate_suggestions(
        exercise=exercise,
        submission=submission,
        config=real_config,
        debug=False,
        is_graded=True,
        learner_profile=None
    )

    # Validate real API responses
    assert len(feedbacks) > 0
    assert all(f.title for f in feedbacks)
    assert all(f.description for f in feedbacks)
```

# Test Data Management

## Mock Test Data

Mock tests use programmatically generated data:

- **In-Memory Objects**: Created within test functions
- **Mock Fixtures**: Reusable mock objects defined in conftest.py
- **Deterministic Responses**: Predictable mock LLM responses
- **No External Files**: All data generated at runtime

## Real Test Data

Real tests use persistent JSON data files:

- **Exercise Files**: Complete exercise definitions with submissions
- **Historical Data**: Real student submissions and feedback
- **Multiple Scenarios**: Various difficulty levels and submission types
- **Version Control**: Data files tracked in git for consistency

## Data File Structure

Real test data follows this JSON structure:

``` json
{
    "id": 6715,
    "course_id": 101,
    "title": "Software Design Patterns",
    "type": "text",
    "max_points": 10,
    "bonus_points": 0,
    "problem_statement": "Explain the following design patterns...",
    "grading_instructions": "Full points for correct identification...",
    "example_solution": "Singleton pattern ensures...",
    "meta": {},
    "submissions": [
        {
            "id": 201,
            "text": "Student submission text...",
            "meta": {},
            "feedbacks": [
                {
                    "id": 301,
                    "title": "Pattern Identification",
                    "description": "Good identification of Singleton pattern",
                    "credits": 2.0,
                    "meta": {}
                }
            ]
        }
    ]
}
```

# When to Use Each Approach

Use Mock Tests When:

- Testing individual functions or methods
- Ensuring code works without external dependencies

Use Real Tests When:

- Validating complete workflows
- Testing API integrations
