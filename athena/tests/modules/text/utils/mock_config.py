from pydantic import BaseModel, Field
from typing import Any, Callable
from module_text_llm.approach_config import ApproachConfig


class MockPrompt(BaseModel):
    system_message: str = "Test system message"
    human_message: str = "Test human message"


class MockModelConfig(BaseModel):
    model_name: str = "azure_openai_gpt-4o-mini"
    
    def get_model(self):
        # Return a mock model that doesn't raise an error
        from unittest.mock import Mock
        mock_model = Mock()
        mock_model.name = "mock-model"
        return mock_model


class MockApproachConfig(ApproachConfig):

    generate_suggestions_prompt: MockPrompt = Field(default_factory=MockPrompt)

    async def generate_suggestions(
        self, exercise, submission, debug=False, is_graded=True
    ):

        return []
