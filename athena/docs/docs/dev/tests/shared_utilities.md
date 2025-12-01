---
title: "Shared Utilities"
---

Athena's testing framework provides a comprehensive set of shared
utilities that enable consistent, efficient, and maintainable testing
across all modules. These utilities are organized hierarchically to
maximize reusability while allowing module-specific customizations.

# Utility Organization

The shared utilities are organized in a hierarchical structure:

``` text
tests/modules/
├── text/
│   └── utils/                    # Text module shared utilities
│       ├── mock_config.py        # Mock configuration objects
│       ├── mock_env.py           # Mock environment variables
│       ├── mock_llm_config.py    # Mock LLM configuration
│       ├── mock_llm.py           # Mock LLM implementations
│       └── mock_openai.py        # Mock OpenAI API responses
└── {module_type}/
    └── module_{module_name}/
        ├── mock/
        │   └── utils/            # Module-specific mock utilities
        └── real/
            └── utils/            # Module-specific real test utilities
```

# Core Utility Categories

## Mock Configuration Utilities

### MockApproachConfig

Provides standardized mock configuration objects for testing:

``` python
class MockApproachConfig:
    """Mock configuration for approach testing."""

    def __init__(self, max_input_tokens=5000, model=None, type="default"):
        self.max_input_tokens = max_input_tokens
        self.model = model or MockModelConfig()
        self.type = type
```

### MockModelConfig

Standardized mock model configuration:

``` python
class MockModelConfig:
    """Mock model configuration for testing."""

    def __init__(self):
        self.model_name = "mock-model"
        self.provider = "mock"
```

## Mock LLM Implementations

### MockLanguageModel 

Base mock LLM implementation with configurable responses:

``` python
class MockLanguageModel:
    """Mock language model for testing."""

    def __init__(self):
        self.responses = {
            "default": "Mock LLM response",
            "feedback": "This is mock feedback.",
            "grading": "Mock grading analysis."
        }

    async def ainvoke(self, prompt):
        """Return mock response based on prompt content."""
        if "feedback" in prompt.lower():
            return self.responses["feedback"]
        elif "grading" in prompt.lower():
            return self.responses["grading"]
        return self.responses["default"]
```

### MockStructuredMockLanguageModel 

Specialized mock for structured output testing:

``` python
class MockStructuredMockLanguageModel(MockLanguageModel):
    """Mock LLM for structured output testing."""

    async def ainvoke(self, prompt):
        """Return structured mock response."""
        return {
            "feedback_suggestions": [
                {
                    "title": "Mock Feedback Title",
                    "description": "Mock feedback description",
                    "credits": 1.0
                }
            ]
        }
```

### MockAssessmentModel 

Mock implementation for assessment and evaluation testing:

``` python
class MockAssessmentModel:
    """Mock assessment model for evaluation testing."""

    async def evaluate(self, submission, feedback):
        """Return mock evaluation results."""
        return {
            "score": 0.85,
            "confidence": 0.92,
            "details": "Mock evaluation details"
        }
```

## Environment Mocking Utilities

### Mock Environment Variables 

Standardized environment variable mocking:

``` python
@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing."""
    mock_vars = {
        "MOCK_MODE": "true",
        "API_KEY": "mock_api_key",
        "MODULE_NAME": "mock_module",
        "MODULE_TYPE": "text",
        "PORT": "5001"
    }

    for key, value in mock_vars.items():
        monkeypatch.setenv(key, value)
```

### Mock API Configuration 

Mock API client configurations:

``` python
class MockOpenAI:
    """Mock OpenAI API client."""

    def __init__(self):
        self.responses = {
            "chat.completions.create": {
                "choices": [{
                    "message": {
                        "content": "Mock OpenAI response"
                    }
                }]
            }
        }

    def chat(self):
        return MockChatCompletion()
```

# Fixture Utilities

## Pytest Fixtures 

Standardized pytest fixtures for consistent test setup:

``` python
@pytest.fixture
def mock_llm():
    """Provide a basic mock language model."""
    return MockLanguageModel()

@pytest.fixture
def mock_structured_llm():
    """Provide a structured mock language model."""
    return MockStructuredMockLanguageModel()

@pytest.fixture
def mock_assessment_model():
    """Provide a mock assessment model."""
    return MockAssessmentModel()

@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return MockApproachConfig(
        max_input_tokens=5000,
        model=MockModelConfig(),
        type="default"
    )
```

## Session-Level Fixtures 

Fixtures that persist across test sessions:

``` python
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment for the entire session."""
    # Download required NLTK data
    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)

    # Setup other session-level configurations
    configure_test_logging()
    setup_test_database()
```

# Test Data Utilities

## Exercise Data Loaders 

Utilities for loading and managing test exercise data:

``` python
class PlaygroundExerciseLoader:
    """Helper class to load exercises from playground data."""

    def __init__(self, data_dir=None):
        if data_dir is None:
            self.data_dir = Path(__file__).parent / "data" / "exercises"
        else:
            self.data_dir = Path(data_dir)

    def load_exercise(self, exercise_id):
        """Load an exercise from JSON file."""
        exercise_file = self.data_dir / f"exercise-{exercise_id}.json"
        if not exercise_file.exists():
            raise FileNotFoundError(f"Exercise file not found: {exercise_file}")

        with open(exercise_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def convert_to_athena_exercise(self, exercise_data):
        """Convert playground data to Athena Exercise object."""
        return Exercise(
            id=exercise_data["id"],
            title=exercise_data["title"],
            type=ExerciseType(exercise_data["type"]),
            max_points=exercise_data["max_points"],
            bonus_points=exercise_data.get("bonus_points", 0),
            grading_instructions=exercise_data.get("grading_instructions", ""),
            problem_statement=exercise_data.get("problem_statement", ""),
            example_solution=exercise_data.get("example_solution", ""),
            grading_criteria=[],
            meta=exercise_data.get("meta", {}),
        )
```

## Submission Data Utilities

Utilities for creating and managing test submissions:

``` python
def create_mock_submission(submission_id=1, text="Mock submission text"):
    """Create a mock submission for testing."""
    return Submission(
        id=submission_id,
        exercise_id=1,
        text=text,
        meta={},
        language=TextLanguageEnum.ENGLISH,
    )

def create_mock_feedback(feedback_id=1, title="Mock Feedback", credits=1.0):
    """Create a mock feedback for testing."""
    return Feedback(
        exercise_id=1,
        submission_id=1,
        title=title,
        description="Mock feedback description",
        credits=credits,
        is_graded=True,
        meta={},
    )
```

# Module-Specific Utilities

## Text Module Utilities

``` python
class TextModuleTestUtils:
    """Utilities specific to text module testing."""

    @staticmethod
    def create_text_exercise(title="Mock Text Exercise"):
        """Create a mock text exercise."""
        return TextExercise(
            id=1,
            title=title,
            type=ExerciseType.text,
            max_points=10,
            problem_statement="Mock problem statement",
            example_solution="Mock example solution"
        )

    @staticmethod
    def create_text_submission(text="Mock submission text"):
        """Create a mock text submission."""
        return Submission(
            id=1,
            exercise_id=1,
            text=text,
            language=TextLanguageEnum.ENGLISH,
            meta={}
        )
```

## Modeling Module Utilities

``` python
class ModelingModuleTestUtils:
    """Utilities specific to modeling module testing."""

    @staticmethod
    def create_modeling_exercise(title="Mock Modeling Exercise"):
        """Create a mock modeling exercise."""
        return ModelingExercise(
            id=1,
            title=title,
            type=ExerciseType.modeling,
            max_points=20,
            problem_statement="Create a UML diagram",
            example_solution="{}"
        )

    @staticmethod
    def create_model_submission(model_data="{}"):
        """Create a mock model submission."""
        return Submission(
            id=1,
            exercise_id=1,
            text="Mock model submission",
            model=model_data,
            meta={}
        )
```

## Programming Module Utilities

``` python
class ProgrammingModuleTestUtils:
    """Utilities specific to programming module testing."""

    @staticmethod
    def create_programming_exercise(title="Mock Programming Exercise"):
        """Create a mock programming exercise."""
        return ProgrammingExercise(
            id=1,
            title=title,
            type=ExerciseType.programming,
            max_points=15,
            programming_language="java",
            solution_repository_uri="http://mock.com/solution.zip",
            template_repository_uri="http://mock.com/template.zip",
            tests_repository_uri="http://mock.com/tests.zip"
        )
```
