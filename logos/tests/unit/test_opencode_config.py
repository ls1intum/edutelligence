"""Tests for opencode config generation."""

import json

import pytest

from logos.opencode_config import generate_opencode_config, generate_opencode_config_json


class TestGenerateOpencodeConfig:
    """Test opencode config generation."""

    def test_produces_valid_json(self):
        config_str = generate_opencode_config_json(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc123",
            available_models=[{"name": "gpt-4", "description": "OpenAI GPT-4"}],
        )
        config = json.loads(config_str)
        assert isinstance(config, dict)

    def test_contains_correct_url(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc123",
            available_models=[{"name": "gpt-4"}],
        )
        # Provider should point to Logos /v1 endpoint
        assert config["providers"]["openai"]["baseURL"] == "https://logos.example.com/v1"

    def test_contains_correct_key(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc123",
            available_models=[{"name": "gpt-4"}],
        )
        assert config["providers"]["openai"]["apiKey"] == "lg-user-abc123"

    def test_includes_available_models(self):
        models = [
            {"name": "gpt-4", "description": "GPT-4"},
            {"name": "llama-3.3-70b", "description": "Llama 3.3"},
        ]
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc123",
            available_models=models,
        )
        assert "gpt-4" in config["logos"]["availableModels"]
        assert "llama-3.3-70b" in config["logos"]["availableModels"]

    def test_default_model_first(self):
        models = [
            {"name": "gpt-4"},
            {"name": "llama-3"},
        ]
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc",
            available_models=models,
        )
        # Default model should be first available
        assert config["agents"]["coder"]["model"] == "gpt-4"

    def test_explicit_default_model(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc",
            available_models=[{"name": "gpt-4"}, {"name": "llama-3"}],
            default_model="llama-3",
        )
        assert config["agents"]["coder"]["model"] == "llama-3"

    def test_empty_models(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc",
            available_models=[],
        )
        assert config["logos"]["availableModels"] == []
        # No agents configured if no models
        assert config["agents"] == {}

    def test_trailing_slash_removed(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com/",
            logos_key="lg-user-abc",
            available_models=[{"name": "gpt-4"}],
        )
        assert config["providers"]["openai"]["baseURL"] == "https://logos.example.com/v1"
        assert config["logos"]["baseUrl"] == "https://logos.example.com"

    def test_schema_present(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc",
            available_models=[{"name": "gpt-4"}],
        )
        assert "$schema" in config

    def test_provider_not_disabled(self):
        config = generate_opencode_config(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc",
            available_models=[{"name": "gpt-4"}],
        )
        assert config["providers"]["openai"]["disabled"] is False

    def test_config_json_is_pretty(self):
        config_str = generate_opencode_config_json(
            logos_base_url="https://logos.example.com",
            logos_key="lg-user-abc",
            available_models=[{"name": "gpt-4"}],
        )
        # Pretty-printed JSON has newlines and indentation
        assert "\n" in config_str
        assert "  " in config_str
