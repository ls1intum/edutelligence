"""Mock configuration classes for testing the text LLM module."""

from pydantic import BaseModel, Field
from typing import Any, Callable
from module_text_llm.approach_config import ApproachConfig

class MockPrompt(BaseModel):
    """Mock prompt template with system and human messages."""
    system_message: str = "Test system message"
    human_message: str = "Test human message"

class MockModelConfig(BaseModel):
    """Mock configuration for language model settings."""
    model_name: str = "mock_model"
    get_model: Callable[[], Any] = Field(default_factory=lambda: lambda: None)

class MockApproachConfig(ApproachConfig):
    """Mock approach configuration for testing."""
    generate_suggestions_prompt: MockPrompt = Field(default_factory=MockPrompt)

    async def generate_suggestions(self, exercise, submission, debug=False, is_graded=True):
        """Mock implementation of generate_suggestions."""
        return []
