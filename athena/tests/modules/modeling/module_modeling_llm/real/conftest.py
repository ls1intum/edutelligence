import pytest
import pytest_asyncio
import asyncio
from typing import List, Dict, Any
from module_modeling_llm.config import BasicApproachConfig
from llm_core.models.providers.azure_model_config import AzureModelConfig


def pytest_configure(config):
    config.option.asyncio_mode = "strict"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the entire test session"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def real_config():
    config = BasicApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(model_name="azure_openai_gpt-4o", get_model=None),
    )
    return config
