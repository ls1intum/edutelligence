import pytest
from pydantic import ConfigDict, Field
from unittest.mock import patch
from typing import Any, Dict, List, Optional, Type
from langchain_community.chat_models.fake import FakeListChatModel
from langchain_core.pydantic_v1 import BaseModel
from llm_core.models.providers.openai_model_config import OpenAIModelConfig
from module_text_llm.default_approach import DefaultApproachConfig
from athena.module_config import ModuleConfig
from athena.schemas.exercise_type import ExerciseType

class FakeChatModel(FakeListChatModel):
    """A fake chat model for testing purposes"""

    requests: List[Dict] = Field(default_factory=list)
    responses: List[Any] = Field(default_factory=list)
    pydantic_object: Optional[Type[BaseModel]] = None

    def get_model(self):
        return self


class FakeModelConfig(OpenAIModelConfig):
    """A fake ModelConfig that extends OpenAIModelConfig for testing"""

    model_name: str = "fake_model"

    def get_model(self, openai_catalog=None):
        """Override to return our fake model"""
        return FakeChatModel()

    model_config = ConfigDict(arbitrary_types_allowed=True)

@pytest.fixture
def mock_sent_tokenize():
    """Provides a mock for the NLTK sent_tokenize function"""
    with patch("module_text_llm.helpers.utils.sent_tokenize") as mock_tokenizer:
        yield mock_tokenizer


@pytest.fixture(autouse=True)
def mock_athena_module_config():
    """Automatically patches the global module config for all tests"""
    stub = ModuleConfig(name="module_text_llm", type=ExerciseType.text, port=5001)
    with patch("athena.module_config.get_module_config", return_value=stub):
        yield


@pytest.fixture
def mock_config():
    """
    Provides a mock configuration object for the text module,
    injecting a fake LLM model config.
    """
    fake_model_config = FakeModelConfig(
        model_name="fake_model",
        provider="openai",
        max_tokens=4000,
        temperature=0.0,
        top_p=1.0,
        presence_penalty=0.0,
        frequency_penalty=0.0,
    )

    return DefaultApproachConfig(model=fake_model_config)
