"""Central configuration for Nebula services."""

import os
from pathlib import Path

import yaml

# Use LangFuse-instrumented OpenAI clients when available for automatic tracing
try:
    from langfuse.openai import AzureOpenAI, OpenAI  # type: ignore[import-not-found]
except ImportError:
    from openai import AzureOpenAI, OpenAI


def get_required_env(name: str) -> str:
    """Get a required environment variable or raise with a clear error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is required but not set.")
    return value


class Config:
    """Central configuration loader for Nebula."""

    # Required: path to LLM config file
    LLM_CONFIG_PATH = Path(get_required_env("LLM_CONFIG_PATH"))

    # Optional: log level (default: INFO)
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def load_llm_config(model: str):
    """Load LLM configuration from a YAML file."""
    config_path = Path(get_required_env("LLM_CONFIG_PATH"))

    if not config_path.is_file():
        raise FileNotFoundError(f"LLM config file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    for entry in config:
        if entry.get("model") == model:
            return entry

    raise ValueError(f"LLM config with model '{model}' not found.")


def get_openai_client(model: str = "gpt-4.1"):
    """
    Create and return an OpenAI or AzureOpenAI client, plus the model/deployment name.
    """
    config = load_llm_config(model=model)
    llm_type = config.get("type")

    if llm_type == "azure_chat":
        return (
            AzureOpenAI(
                azure_endpoint=config["endpoint"],
                azure_deployment=config["azure_deployment"],
                api_key=config["api_key"],
                api_version=config["api_version"],
            ),
            config["azure_deployment"],
        )

    if llm_type == "openai_chat":
        return OpenAI(api_key=config["api_key"]), config["model"]

    raise ValueError(f"Unsupported OpenAI LLM config type: {llm_type}")
