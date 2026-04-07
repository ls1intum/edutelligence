import os
import pytest
from unittest.mock import patch
from atlasml.config import (
    Settings,
    APIKeyConfig,
    WeaviateSettings,
    get_settings,
    reset_settings,
)


class TestSettings:
    """Test class for Settings configuration."""

    def test_get_settings_with_valid_env_vars(self):
        """Test that settings are loaded correctly from environment variables."""
        env_vars = {
            "ATLAS_API_KEYS": "token1,token2,token3",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()

            # Test API keys
            assert len(settings.api_keys) == 3
            assert settings.api_keys[0].token == "token1"
            assert settings.api_keys[1].token == "token2"
            assert settings.api_keys[2].token == "token3"

            # Test Weaviate settings
            assert settings.weaviate.host == "localhost"
            assert settings.weaviate.port == 8080

    def test_get_settings_with_single_api_key(self):
        """Test that settings work with a single API key."""
        env_vars = {
            "ATLAS_API_KEYS": "single-token",
            "WEAVIATE_HOST": "test-host",
            "WEAVIATE_PORT": "9090",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()

            assert len(settings.api_keys) == 1
            assert settings.api_keys[0].token == "single-token"

    def test_get_settings_with_spaces_in_api_keys(self):
        """Test that API keys with spaces are trimmed correctly."""
        env_vars = {
            "ATLAS_API_KEYS": " token1 , token2 , token3 ",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()

            assert len(settings.api_keys) == 3
            assert settings.api_keys[0].token == "token1"
            assert settings.api_keys[1].token == "token2"
            assert settings.api_keys[2].token == "token3"

    def test_missing_atlas_api_keys(self):
        """Test that missing ATLAS_API_KEYS raises ValueError."""
        env_vars = {
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="Missing required environment variables: ATLAS_API_KEYS",
            ):
                Settings.get_settings()

    def test_missing_weaviate_host(self):
        """Test that missing WEAVIATE_HOST raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="Missing required environment variables: WEAVIATE_HOST",
            ):
                Settings.get_settings()

    def test_missing_weaviate_port(self):
        """Test that missing WEAVIATE_PORT raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="Missing required environment variables: WEAVIATE_PORT",
            ):
                Settings.get_settings()

    def test_valid_settings_without_grpc(self):
        """Test that settings work without gRPC port (REST only)."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()
            assert settings.weaviate.host == "localhost"
            assert settings.weaviate.port == 8080

    def test_missing_multiple_env_vars(self):
        """Test that missing multiple environment variables are reported correctly."""
        env_vars = {"ATLAS_API_KEYS": "token1"}

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="Missing required environment variables: WEAVIATE_HOST, WEAVIATE_PORT",
            ):
                Settings.get_settings()

    def test_empty_atlas_api_keys(self):
        """Test that empty ATLAS_API_KEYS raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="Missing required environment variables: ATLAS_API_KEYS",
            ):
                Settings.get_settings()

    def test_whitespace_only_atlas_api_keys(self):
        """Test that whitespace-only ATLAS_API_KEYS raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "   ,  ,   ",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="ATLAS_API_KEYS must contain at least one valid API key",
            ):
                Settings.get_settings()

    def test_invalid_weaviate_port(self):
        """Test that invalid WEAVIATE_PORT raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "invalid-port",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Invalid port configuration"):
                Settings.get_settings()

    def test_https_weaviate_host_parsing(self):
        """Test that HTTPS Weaviate host strings parse scheme and hostname correctly."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "https://weaviate.example.com",
            "WEAVIATE_PORT": "443",
            "WEAVIATE_API_KEY": "secret-key",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()
            assert settings.weaviate.scheme == "https"
            assert settings.weaviate.host == "weaviate.example.com"
            assert settings.weaviate.port == 443
            assert settings.weaviate.api_key == "secret-key"

    def test_http_weaviate_host_with_scheme(self):
        """Test that HTTP hosts with scheme are normalized correctly."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "http://weaviate.internal",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()
            assert settings.weaviate.scheme == "http"
            assert settings.weaviate.host == "weaviate.internal"
            assert settings.weaviate.port == 8080

    def test_https_without_api_key_fails(self):
        """Test that HTTPS connections require API key."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "https://weaviate.example.com",
            "WEAVIATE_PORT": "443",
            # No WEAVIATE_API_KEY
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="WEAVIATE_API_KEY is required when using HTTPS",
            ):
                Settings.get_settings()

    def test_production_without_api_key_fails(self):
        """Test that production environment requires API key."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "weaviate.internal",
            "WEAVIATE_PORT": "8080",
            "ENV": "production",
            # No WEAVIATE_API_KEY
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(
                ValueError,
                match="WEAVIATE_API_KEY is required in production",
            ):
                Settings.get_settings()

    def test_production_with_https_and_api_key_succeeds(self):
        """Test that production with HTTPS and API key works correctly."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "https://weaviate.example.com",
            "WEAVIATE_PORT": "443",
            "WEAVIATE_API_KEY": "prod-weaviate-key",
            "ENV": "production",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.get_settings()
            assert settings.weaviate.scheme == "https"
            assert settings.weaviate.api_key == "prod-weaviate-key"
            assert settings.env == "production"

    def test_get_api_keys_method(self):
        """Test the get_api_keys class method."""
        env_vars = {
            "ATLAS_API_KEYS": "key1,key2",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            api_keys = Settings.get_api_keys()

            assert len(api_keys) == 2
            assert api_keys[0].token == "key1"
            assert api_keys[1].token == "key2"
            assert all(isinstance(key, APIKeyConfig) for key in api_keys)

    def test_default_settings(self):
        """Test that default settings work for testing."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.get_settings(use_defaults=True)

            assert len(settings.api_keys) == 1
            assert settings.api_keys[0].token == "default-test-token"
            assert settings.weaviate.host == "localhost"
            assert settings.weaviate.port == 8080

    def test_auto_detect_test_environment(self):
        """Test that test environment is auto-detected."""
        test_env_vars = {"PYTEST_CURRENT_TEST": "true"}

        with patch.dict(os.environ, test_env_vars, clear=True):
            settings = Settings.get_settings()

            # Should use defaults because test environment is detected
            assert len(settings.api_keys) == 1
            assert settings.api_keys[0].token == "default-test-token"

    def test_global_settings_function(self):
        """Test the global get_settings function."""
        # Reset any cached settings
        reset_settings()

        env_vars = {
            "ATLAS_API_KEYS": "global-test-key",
            "WEAVIATE_HOST": "test-host",
            "WEAVIATE_PORT": "9090",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = get_settings()

            assert len(settings.api_keys) == 1
            assert settings.api_keys[0].token == "global-test-key"
            assert settings.weaviate.host == "test-host"
            assert settings.weaviate.port == 9090

            # Test that it returns the same instance (caching)
            settings2 = get_settings()
            assert settings is settings2

    def test_reset_settings(self):
        """Test the reset_settings function."""
        # Reset settings before test
        reset_settings()

        # First, get settings
        env_vars = {
            "ATLAS_API_KEYS": "test-reset-key",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings1 = get_settings()

            # Verify first settings
            assert settings1.api_keys[0].token == "test-reset-key"

            # Reset settings
            reset_settings()

            # Get settings again - should be a new instance with same values
            settings2 = get_settings()

            # They should have the same values
            assert settings1.api_keys[0].token == settings2.api_keys[0].token
            assert settings1.weaviate.host == settings2.weaviate.host


class TestAPIKeyConfig:
    """Test class for APIKeyConfig model."""

    def test_api_key_config_creation(self):
        """Test APIKeyConfig creation with valid token."""
        config = APIKeyConfig(token="test-token")
        assert config.token == "test-token"

    def test_api_key_config_validation(self):
        """Test APIKeyConfig validation."""
        # Should work with any string
        config = APIKeyConfig(token="")
        assert config.token == ""

        config = APIKeyConfig(token="very-long-token-with-special-chars-123!@#")
        assert config.token == "very-long-token-with-special-chars-123!@#"


class TestWeaviateSettings:
    """Test class for WeaviateSettings model."""

    def test_weaviate_settings_creation(self):
        """Test WeaviateSettings creation with valid values."""
        settings = WeaviateSettings(host="localhost", port=8080)
        assert settings.host == "localhost"
        assert settings.port == 8080
        assert settings.scheme == "http"  # default scheme

    def test_weaviate_settings_validation(self):
        """Test WeaviateSettings validation with different values."""
        # Test with different host formats
        settings = WeaviateSettings(host="192.168.1.1", port=9090)
        assert settings.host == "192.168.1.1"
        assert settings.port == 9090

        # Test with domain name
        settings = WeaviateSettings(
            host="weaviate.example.com", port=443
        )
        assert settings.host == "weaviate.example.com"
        assert settings.port == 443
