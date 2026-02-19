"""
Generate opencode configuration files for Logos users.

opencode (.opencode.json) supports OpenAI-compatible providers
via the LOCAL_ENDPOINT environment variable or custom provider config.
This module generates a config file that points to Logos as the provider.
"""

import json
from typing import List, Optional


def generate_opencode_config(
    logos_base_url: str,
    logos_key: str,
    available_models: List[dict],
    default_model: Optional[str] = None,
) -> dict:
    """
    Generate an opencode configuration dict for a Logos user.

    Args:
        logos_base_url: The base URL of the Logos instance (e.g. https://logos.example.com)
        logos_key: The user's Logos API key
        available_models: List of dicts with at least 'name' key for each model
        default_model: The default model to use (if None, uses first available)

    Returns:
        Dict representing a valid .opencode.json config
    """
    # Normalize base URL (remove trailing slash)
    base_url = logos_base_url.rstrip("/")

    # Pick default model
    model_names = [m["name"] for m in available_models if m.get("name")]
    if not default_model and model_names:
        default_model = model_names[0]

    # opencode uses LOCAL_ENDPOINT for self-hosted providers
    # The config references models as "local.<model_name>"
    # Build model name for opencode (local provider prefix)
    default_model_ref = f"local.{default_model}" if default_model else None

    config = {
        "$schema": "https://raw.githubusercontent.com/opencode-ai/opencode/main/opencode-schema.json",
        "providers": {
            "openai": {
                "apiKey": logos_key,
                "baseURL": f"{base_url}/v1",
                "disabled": False,
            },
        },
        "agents": {},
        "logos": {
            "baseUrl": base_url,
            "apiKey": logos_key,
            "availableModels": model_names,
        },
    }

    if default_model_ref:
        config["agents"]["coder"] = {
            "model": default_model,
            "maxTokens": 8192,
        }
        config["agents"]["task"] = {
            "model": default_model,
            "maxTokens": 8192,
        }
        config["agents"]["title"] = {
            "model": default_model,
            "maxTokens": 80,
        }

    return config


def generate_opencode_config_json(
    logos_base_url: str,
    logos_key: str,
    available_models: List[dict],
    default_model: Optional[str] = None,
) -> str:
    """
    Generate opencode configuration as a formatted JSON string.

    Args:
        logos_base_url: The base URL of the Logos instance
        logos_key: The user's Logos API key
        available_models: List of model dicts
        default_model: Default model name

    Returns:
        Formatted JSON string for .opencode.json
    """
    config = generate_opencode_config(
        logos_base_url, logos_key, available_models, default_model
    )
    return json.dumps(config, indent=2)
