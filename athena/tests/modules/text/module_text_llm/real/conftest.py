import pytest
import nltk
import asyncio
from typing import List, Dict, Any
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


# ============================================================================
# MODEL CONFIGURATIONS
# ============================================================================

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

@pytest.fixture
def gpt4o_config():
    """Create a basic configuration for testing with GPT-4o."""
    return DefaultApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",
            get_model=lambda: None,
        ),
        type="default",
    )


@pytest.fixture
def gpt4_turbo_config():
    """Create a basic configuration for testing with GPT-4-turbo."""
    return DefaultApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4-turbo",
            get_model=lambda: None,
        ),
        type="default",
    )


@pytest.fixture
def gpt35_turbo_config():
    """Create a basic configuration for testing with GPT-3.5-turbo."""
    return DefaultApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-35-turbo",
            get_model=lambda: None,
        ),
        type="default",
    )


@pytest.fixture
def chain_of_thought_config():
    """Create a chain of thought configuration for testing."""
    return ChainOfThoughtConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",
            get_model=lambda: None,  # This will be set by the module
        ),
        type="chain_of_thought",
    )


# ============================================================================
# QUALITY DRIFT ANALYSIS CONFIGURATIONS
# ============================================================================

def get_model_configs() -> List[Dict[str, Any]]:
    """Get list of all model configurations for quality drift analysis."""
    return [
        {
            "name": "gpt-4o",
            "config": DefaultApproachConfig(
                max_input_tokens=5000,
                model=AzureModelConfig(
                    model_name="azure_openai_gpt-4o",
                    get_model=lambda: None,
                ),
                type="default",
            )
        },
        {
            "name": "gpt-4-turbo", 
            "config": DefaultApproachConfig(
                max_input_tokens=5000,
                model=AzureModelConfig(
                    model_name="azure_openai_gpt-4-turbo",
                    get_model=lambda: None,
                ),
                type="default",
            )
        },
        {
            "name": "gpt-35-turbo",
            "config": DefaultApproachConfig(
                max_input_tokens=5000,
                model=AzureModelConfig(
                    model_name="azure_openai_gpt-35-turbo",
                    get_model=lambda: None,
                ),
                type="default",
            )
        }
    ]


# ============================================================================
# BASELINE GENERATION CONFIGURATION
# ============================================================================

@pytest.fixture
def baseline_config():
    """Create a configuration for baseline generation using GPT-4o."""
    return DefaultApproachConfig(
        max_input_tokens=5000,
        model=AzureModelConfig(
            model_name="azure_openai_gpt-4o",
            get_model=lambda: None,
        ),
        type="default",
    )
