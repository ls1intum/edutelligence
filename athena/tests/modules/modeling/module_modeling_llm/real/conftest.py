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
    """Create an instance of the default event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def real_config():
    config = BasicApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",  
            get_model=None  
        )
    )
    return config

@pytest.fixture
def gpt4o_config():
    """Create a basic configuration for testing with GPT-4o."""
    return BasicApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",
            get_model=None,
        ),
    )

@pytest.fixture
def gpt4_turbo_config():
    """Create a basic configuration for testing with GPT-4-turbo."""
    return BasicApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4-turbo",
            get_model=None,
        ),
    )

@pytest.fixture
def gpt35_turbo_config():
    """Create a basic configuration for testing with GPT-3.5-turbo."""
    return BasicApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-35-turbo",
            get_model=None,
        ),
    )

# ============================================================================
# QUALITY DRIFT ANALYSIS CONFIGURATIONS
# ============================================================================

def get_model_configs() -> List[Dict[str, Any]]:
    """Get list of all model configurations for quality drift analysis."""
    return [
        {
            "name": "gpt-4o",
            "config": BasicApproachConfig(
                max_input_tokens=5000,
                model=AzureModelConfig(
                    model_name="azure_openai_gpt-4o",
                    get_model=None,
                ),
            )
        },
        {
            "name": "gpt-4-turbo", 
            "config": BasicApproachConfig(
                max_input_tokens=5000,
                model=AzureModelConfig(
                    model_name="azure_openai_gpt-4-turbo",
                    get_model=None,
                ),
            )
        },
        {
            "name": "gpt-35-turbo",
            "config": BasicApproachConfig(
                max_input_tokens=5000,
                model=AzureModelConfig(
                    model_name="azure_openai_gpt-35-turbo",
                    get_model=None,
                ),
            )
        }
    ]

# ============================================================================
# BASELINE GENERATION CONFIGURATION
# ============================================================================

@pytest.fixture
def baseline_config():
    """Create a configuration for baseline generation using GPT-4o."""
    return BasicApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",
            get_model=None,
        ),
    )