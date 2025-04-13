"""Mock environment setup for testing the text LLM module."""

import os
import sys
from unittest.mock import Mock

# Mock OpenAI
class MockOpenAIModelConfig:
    """Mock configuration for OpenAI model settings."""
    model_name = "mock_model"
    get_model = lambda self: Mock()

mock_openai = Mock()
mock_openai.OpenAIModelConfig = MockOpenAIModelConfig
mock_openai.available_models = {'mock_model': Mock()}
sys.modules['llm_core.models.openai'] = mock_openai

# Env vars
os.environ["LLM_DEFAULT_MODEL"] = "mock_model"
os.environ["LLM_EVALUATION_MODEL"] = "mock_model"
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_BASE"] = "mock_base"

# Mock NLTK
mock_sent_tokenize = Mock()
mock_sent_tokenize.return_value = ["This is a test sentence."]
mock_nltk = Mock()
mock_nltk.tokenize = Mock()
mock_nltk.tokenize.sent_tokenize = mock_sent_tokenize
mock_nltk.sent_tokenize = mock_sent_tokenize 
sys.modules['nltk'] = mock_nltk
sys.modules['nltk.tokenize'] = mock_nltk.tokenize

# Patch configparser
from unittest.mock import patch

class MockConfigParser:
    """Mock implementation of ConfigParser for module configuration."""
    def __init__(self):
        self._data = {"module": {"name": "text", "type": "text", "port": "8000"}}

    def __getitem__(self, key):
        return self._data[key]

    def read(self, *args, **kwargs):
        pass

with patch("athena.module_config.configparser.ConfigParser", return_value=MockConfigParser()):
    from athena.module_config import get_module_config
