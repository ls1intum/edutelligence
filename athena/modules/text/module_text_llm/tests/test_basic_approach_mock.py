"""
Test suite for the basic approach of text LLM module.

This test suite verifies the functionality of the text LLM module's basic approach for generating
feedback on student submissions. It includes tests for various scenarios including basic submissions,
empty submissions, and long input submissions.

The tests use extensive mocking to isolate the functionality being tested:
- Mocks OpenAI model configuration and environment variables
- Mocks NLTK's sentence tokenization
- Mocks module configuration and config parser
- Mocks language model responses

Each test case focuses on a specific aspect of the feedback generation process.
"""

import pytest
from unittest.mock import Mock, patch
import os
import sys
from typing import Optional, List, Callable, Any
from pydantic import BaseModel, Field
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import PromptValue

# Mock OpenAI model configuration
class MockOpenAIModelConfig(BaseModel):
    """Mock configuration for OpenAI model settings."""
    model_name: str = "mock_model"
    get_model: Callable[[], Any] = Field(default_factory=lambda: Mock())

# Mock OpenAI configuration and environment setup
mock_openai = Mock()
mock_openai.OpenAIModelConfig = MockOpenAIModelConfig
mock_openai.available_models = {'mock_model': Mock()}
sys.modules['llm_core.models.openai'] = mock_openai

# Set up mock environment variables for API keys and model configurations
os.environ["LLM_DEFAULT_MODEL"] = "mock_model"
os.environ["LLM_EVALUATION_MODEL"] = "mock_model"
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_BASE"] = "mock_base"

# Mock NLTK's sentence tokenization for text processing
mock_sent_tokenize = Mock()
mock_sent_tokenize.return_value = ["This is a test sentence."]
mock_nltk = Mock()
mock_nltk.tokenize = Mock()
mock_nltk.tokenize.sent_tokenize = mock_sent_tokenize
sys.modules['nltk'] = mock_nltk
sys.modules['nltk.tokenize'] = mock_nltk.tokenize

# Mock configuration parser for module settings
class MockConfigParser:
    """Mock implementation of ConfigParser for module configuration.
    
    This mock provides the necessary configuration data without reading from actual files.
    It simulates the module configuration with predefined values for name, type, and port.
    """
    def __init__(self):
        self._data = {"module": {"name": "text", "type": "text", "port": "8000"}}

    def __getitem__(self, key):
        return self._data[key]

    def read(self, *args, **kwargs):
        """Mock read method that does nothing since we're using predefined data."""
        pass

# Patch the config parser and import necessary modules
with patch("athena.module_config.configparser.ConfigParser", return_value=MockConfigParser()):
    from athena.module_config import get_module_config
    from athena.text import Exercise, Submission, Feedback
    from module_text_llm.approach_config import ApproachConfig
    from athena.schemas.exercise_type import ExerciseType
    from module_text_llm.basic_approach.prompt_generate_suggestions import AssessmentModel
    from module_text_llm.basic_approach.generate_suggestions import generate_suggestions

# Mock model configuration for testing
class MockModelConfig(BaseModel):
    """Mock configuration for the language model."""
    model_name: str = "mock_model"
    get_model: Callable[[], Any] = Field(default_factory=lambda: Mock())

# Mock prompt template for testing
class MockPrompt(BaseModel):
    """Mock prompt template with system and human messages."""
    system_message: str = "Test system message"
    human_message: str = "Test human message"

# Mock feedback model for testing
class MockFeedbackModel(BaseModel):
    """Mock feedback model representing individual feedback items.
    
    Attributes:
        title: Title of the feedback
        description: Detailed description of the feedback
        line_start: Starting line number (optional)
        line_end: Ending line number (optional)
        credits: Points awarded (optional)
        grading_instruction_id: ID of the grading instruction (optional)
    """
    title: str = "Test Feedback"
    description: str = "Test description"
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    credits: float = 0.0
    grading_instruction_id: Optional[int] = None

# Mock assessment model for testing
class MockAssessmentModel(BaseModel):
    """Mock assessment model containing a list of feedback items."""
    feedbacks: List[MockFeedbackModel] = Field(default_factory=lambda: [MockFeedbackModel()])

# Mock language model implementation
class MockLanguageModel(BaseLanguageModel):
    """Mock implementation of a language model for testing.
    
    This mock implements the LangChain interface and returns predefined responses
    for various language model operations.
    """
    return_value: Any = Field(default_factory=lambda: MockAssessmentModel())

    def __init__(self, return_value: Any = None):
        super().__init__()
        if return_value is not None:
            self.return_value = return_value

    async def ainvoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        return self.return_value

    def with_structured_output(self, cls: Any) -> Any:
        return self

    async def agenerate_prompt(self, prompts: List[PromptValue], stop: Optional[List[str]] = None, **kwargs: Any) -> Any:
        return [self.return_value]

    async def apredict(self, text: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    async def apredict_messages(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    def generate_prompt(self, prompts: List[PromptValue], stop: Optional[List[str]] = None, **kwargs: Any) -> Any:
        return [self.return_value]

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        return self.return_value

    def predict(self, text: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

    def predict_messages(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        return str(self.return_value)

# Mock approach configuration
class MockApproachConfig(ApproachConfig):
    """Mock approach configuration for testing the basic approach.
    
    This class extends the actual ApproachConfig and provides mock implementations
    of the necessary methods for testing.
    """
    generate_suggestions_prompt: MockPrompt = Field(default_factory=MockPrompt)
    
    async def generate_suggestions(self, exercise, submission, debug=False, is_graded=True):
        return []

@pytest.fixture
def mock_exercise():
    """Fixture providing a mock exercise for testing.
    
    Returns:
        Exercise: A mock exercise with predefined values for testing feedback generation.
    """
    return Exercise(
        id=1,
        title="Test Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="Test grading instructions",
        problem_statement="Test problem statement",
        example_solution="Test example solution",
        grading_criteria=[]
    )

@pytest.fixture
def mock_submission(mock_exercise):
    """Fixture providing a mock submission for testing.
    
    Args:
        mock_exercise: The mock exercise fixture to associate the submission with.
    
    Returns:
        Submission: A mock submission with predefined text content.
    """
    return Submission(
        id=1,
        exerciseId=mock_exercise.id,
        text="This is a test submission.\nIt has multiple lines.\nFor testing purposes."
    )

@pytest.fixture
def mock_config():
    """Fixture providing a mock configuration for testing.
    
    Returns:
        MockApproachConfig: A mock configuration with predefined settings.
    """
    config = MockApproachConfig(
        max_input_tokens=5000,
        model=MockModelConfig(),
        type="basic"
    )
    return config

@pytest.mark.asyncio
async def test_generate_suggestions_basic(mock_exercise, mock_submission, mock_config):
    """Test basic feedback generation with a simple submission.
    
    This test verifies that the feedback generation works correctly with a standard submission.
    It checks that:
    - The returned feedback is a list
    - All items in the list are Feedback objects
    - The feedback is correctly associated with the exercise and submission
    """
    mock_model = MockLanguageModel(return_value=AssessmentModel(feedbacks=[
        MockFeedbackModel(
            title="Test Feedback",
            description="Test description",
            line_start=1,
            line_end=2,
            credits=5.0
        )
    ]))
    mock_config.model.get_model = lambda: mock_model
    
    # Update mock_sent_tokenize for this test
    mock_sent_tokenize.return_value = [
        "This is a test submission.",
        "It has multiple lines.",
        "For testing purposes."
    ]
    
    feedbacks = await generate_suggestions(
        exercise=mock_exercise,
        submission=mock_submission,
        config=mock_config,
        debug=False,
        is_graded=True
    )
    
    assert isinstance(feedbacks, list)
    assert all(isinstance(feedback, Feedback) for feedback in feedbacks)
    assert all(feedback.exercise_id == mock_exercise.id for feedback in feedbacks)
    assert all(feedback.submission_id == mock_submission.id for feedback in feedbacks)

@pytest.mark.asyncio
async def test_generate_suggestions_empty_submission(mock_exercise, mock_config):
    """Test feedback generation with an empty submission.
    
    This test verifies that the system handles empty submissions correctly.
    It checks that:
    - The returned feedback is an empty list
    - No errors are raised when processing empty submissions
    """
    empty_submission = Submission(
        id=2,
        exerciseId=mock_exercise.id,
        text=""
    )
    
    mock_model = MockLanguageModel(return_value=AssessmentModel(feedbacks=[]))
    mock_config.model.get_model = lambda: mock_model
    
    # Update mock_sent_tokenize for this test
    mock_sent_tokenize.return_value = []
    
    feedbacks = await generate_suggestions(
        exercise=mock_exercise,
        submission=empty_submission,
        config=mock_config,
        debug=False,
        is_graded=True
    )
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) == 0

@pytest.mark.asyncio
async def test_generate_suggestions_long_input(mock_exercise, mock_config):
    """Test feedback generation with a very long submission.
    
    This test verifies that the system can handle submissions with large amounts of text.
    It checks that:
    - The system can process long inputs without errors
    - Feedback is generated correctly for long submissions
    - The feedback is properly associated with the exercise and submission
    """
    long_submission = Submission(
        id=3,
        exerciseId=mock_exercise.id,
        text="Test " * 1000  # Very long text
    )
    
    mock_model = MockLanguageModel(return_value=AssessmentModel(feedbacks=[
        MockFeedbackModel(
            title="Test Long Input Feedback",
            description="Test description for long input",
            line_start=1,
            line_end=100,
            credits=7.0
        )
    ]))
    mock_config.model.get_model = lambda: mock_model
    
    # Update mock_sent_tokenize for this test
    mock_sent_tokenize.return_value = ["Test " * 100 for _ in range(10)]
    
    feedbacks = await generate_suggestions(
        exercise=mock_exercise,
        submission=long_submission,
        config=mock_config,
        debug=False,
        is_graded=True
    )
    
    assert isinstance(feedbacks, list)
    assert all(isinstance(feedback, Feedback) for feedback in feedbacks)
    assert all(feedback.exercise_id == mock_exercise.id for feedback in feedbacks)
    assert all(feedback.submission_id == long_submission.id for feedback in feedbacks) 