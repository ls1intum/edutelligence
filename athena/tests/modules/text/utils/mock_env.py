import os
import sys
from unittest.mock import Mock, patch

# Import OpenAI mocks first
from tests.modules.text.utils.mock_openai import mock_openai, mock_openai_client

# Env vars
os.environ["LLM_DEFAULT_MODEL"] = "mock_model"
os.environ["LLM_EVALUATION_MODEL"] = "mock_model"
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_KEY"] = "mock_key"
os.environ["AZURE_OPENAI_API_BASE"] = "mock_base"

# Mock NLTK


def mock_sent_tokenize(text):
    """Mock implementation of sent_tokenize that splits on periods."""
    return [s.strip() for s in text.split('.') if s.strip()]


patch('module_text_llm.helpers.utils.sent_tokenize', mock_sent_tokenize).start()

# Mock the entire nltk package
mock_nltk = Mock()
mock_nltk.tokenize = Mock()
mock_nltk.tokenize.sent_tokenize = mock_sent_tokenize
mock_nltk.sent_tokenize = mock_sent_tokenize

sys.modules['nltk'] = mock_nltk
sys.modules['nltk.tokenize'] = mock_nltk.tokenize
sys.modules['nltk.tokenize.punkt'] = Mock()
