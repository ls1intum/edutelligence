import pytest
import nltk
import asyncio
from module_text_llm.default_approach import DefaultApproachConfig
from llm_core.models.providers.azure_model_config import AzureModelConfig


@pytest.fixture(scope="session", autouse=True)
def setup_environment():

    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def real_config():
    """Create a real configuration for testing with Azure OpenAI"""
    return DefaultApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o", get_model=lambda: None
        ),
        type="default",
    )
