import os
import sys
from unittest.mock import Mock
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, Callable
from langchain.base_language import BaseLanguageModel

# Import OpenAI mocks first
from tests.modules.programming.module_programming_llm.mock.utils.mock_openai import mock_openai, mock_openai_client
from tests.modules.programming.module_programming_llm.mock.utils.mock_llm import MockLanguageModel

# Set up mock environment variables
os.environ["LLM_DEFAULT_MODEL"] = "mock_model"
os.environ["LLM_EVALUATION_MODEL"] = "mock_model"
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_BASE"] = "mock_base"

# Create proper Pydantic models for mocking
class MockModelConfigType(BaseModel):
    model_name: str = Field(default="mock_model")
    model_params: Dict[str, Any] = Field(default_factory=lambda: {
        "temperature": 0.7,
        "max_tokens": 1000,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
    })

    class Config:
        arbitrary_types_allowed = True

class MockDefaultModelConfig(MockModelConfigType):
    pass

# Create ModelConfig mock
class MockModelConfig(BaseModel):
    model_name: str = "azure_openai_gpt-4-turbo"
    get_model_func: Optional[Callable[[], BaseLanguageModel]] = None
    model_params: Dict[str, Any] = {
        "temperature": 0.7,
        "max_tokens": 1000,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
    }

    def get_model(self) -> BaseLanguageModel:
        if self.get_model_func is not None:
            return self.get_model_func()
        return MockLanguageModel()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            **self.model_params
        }

    class Config:
        arbitrary_types_allowed = True

# Mock llm_core models
mock_llm_core = Mock()
mock_llm_core.models = Mock()
mock_llm_core.models.ModelConfigType = MockModelConfigType
mock_llm_core.models.DefaultModelConfig = MockDefaultModelConfig
mock_llm_core.models.get_model_configs = lambda: {
    "mock_model": MockDefaultModelConfig()
}

# Mock model_config module
mock_model_config = Mock()
mock_model_config.ModelConfig = MockModelConfig
sys.modules['llm_core.models.model_config'] = mock_model_config

# Apply the mock to sys.modules
sys.modules['llm_core'] = mock_llm_core
sys.modules['llm_core.models'] = mock_llm_core.models 