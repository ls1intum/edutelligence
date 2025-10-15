import sys
from unittest.mock import Mock, patch
from pydantic import ConfigDict, BaseModel, Field
from typing import Any, Callable

# Mock ConfigParser first


class MockConfigParser:
    """Mock implementation of ConfigParser for module configuration."""

    def __init__(self):
        self._data = {
            "module": {
                "name": "text",
                "type": "text",
                "port": "8000"}}

    def __getitem__(self, key):
        return self._data[key]

    def read(self, *args, **kwargs):
        pass


# Apply ConfigParser patch
patcher = patch(
    "athena.module_config.configparser.ConfigParser",
    return_value=MockConfigParser())
patcher.start()

# Mock OpenAI - this must be done before any other imports


class MockOpenAIModelConfig(BaseModel):
    """Mock configuration for OpenAI model settings."""
    model_name: str = "mock_model"
    get_model: Callable[[], Any] = Field(default_factory=lambda: Mock())
    model_config = ConfigDict(arbitrary_types_allowed=True)


mock_openai = Mock()
mock_openai.OpenAIModelConfig = MockOpenAIModelConfig
mock_openai.available_models = {'mock_model': Mock()}
sys.modules['llm_core.models.openai'] = mock_openai

# Mock OpenAI client
mock_openai_client = Mock()
mock_openai_client.models.list.return_value = []
sys.modules['openai'] = mock_openai_client
