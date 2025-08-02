import os
import pytest
from unittest.mock import patch
from atlasml.config import Settings, APIKeyConfig, WeaviateSettings


class TestSettings:
    """Test class for Settings configuration."""

    def test_get_settings_with_valid_env_vars(self):
        """Test that settings are loaded correctly from environment variables."""
        env_vars = {
            "ATLAS_API_KEYS": "token1,token2,token3",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
            "WEAVIATE_GRPC_PORT": "50051"
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
            assert settings.weaviate.grpc_port == 50051

    def test_get_settings_with_single_api_key(self):
        """Test that settings work with a single API key."""
        env_vars = {
            "ATLAS_API_KEYS": "single-token",
            "WEAVIATE_HOST": "test-host",
            "WEAVIATE_PORT": "9090",
            "WEAVIATE_GRPC_PORT": "60051"
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
            "WEAVIATE_GRPC_PORT": "50051"
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
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Missing required environment variables: ATLAS_API_KEYS"):
                Settings.get_settings()

    def test_missing_weaviate_host(self):
        """Test that missing WEAVIATE_HOST raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_PORT": "8080",
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Missing required environment variables: WEAVIATE_HOST"):
                Settings.get_settings()

    def test_missing_weaviate_port(self):
        """Test that missing WEAVIATE_PORT raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Missing required environment variables: WEAVIATE_PORT"):
                Settings.get_settings()

    def test_missing_weaviate_grpc_port(self):
        """Test that missing WEAVIATE_GRPC_PORT raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Missing required environment variables: WEAVIATE_GRPC_PORT"):
                Settings.get_settings()

    def test_missing_multiple_env_vars(self):
        """Test that missing multiple environment variables are reported correctly."""
        env_vars = {
            "ATLAS_API_KEYS": "token1"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Missing required environment variables: WEAVIATE_HOST, WEAVIATE_PORT, WEAVIATE_GRPC_PORT"):
                Settings.get_settings()

    def test_empty_atlas_api_keys(self):
        """Test that empty ATLAS_API_KEYS raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Missing required environment variables: ATLAS_API_KEYS"):
                Settings.get_settings()

    def test_whitespace_only_atlas_api_keys(self):
        """Test that whitespace-only ATLAS_API_KEYS raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "   ,  ,   ",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="ATLAS_API_KEYS must contain at least one valid API key"):
                Settings.get_settings()

    def test_invalid_weaviate_port(self):
        """Test that invalid WEAVIATE_PORT raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "invalid-port",
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Invalid port configuration"):
                Settings.get_settings()

    def test_invalid_weaviate_grpc_port(self):
        """Test that invalid WEAVIATE_GRPC_PORT raises ValueError."""
        env_vars = {
            "ATLAS_API_KEYS": "token1",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
            "WEAVIATE_GRPC_PORT": "invalid-grpc-port"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Invalid port configuration"):
                Settings.get_settings()

    def test_get_api_keys_method(self):
        """Test the get_api_keys class method."""
        env_vars = {
            "ATLAS_API_KEYS": "key1,key2",
            "WEAVIATE_HOST": "localhost",
            "WEAVIATE_PORT": "8080",
            "WEAVIATE_GRPC_PORT": "50051"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            api_keys = Settings.get_api_keys()
            
            assert len(api_keys) == 2
            assert api_keys[0].token == "key1"
            assert api_keys[1].token == "key2"
            assert all(isinstance(key, APIKeyConfig) for key in api_keys)


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
        settings = WeaviateSettings(host="localhost", port=8080, grpc_port=50051)
        assert settings.host == "localhost"
        assert settings.port == 8080
        assert settings.grpc_port == 50051

    def test_weaviate_settings_validation(self):
        """Test WeaviateSettings validation with different values."""
        # Test with different host formats
        settings = WeaviateSettings(host="192.168.1.1", port=9090, grpc_port=60051)
        assert settings.host == "192.168.1.1"
        assert settings.port == 9090
        assert settings.grpc_port == 60051
        
        # Test with domain name
        settings = WeaviateSettings(host="weaviate.example.com", port=443, grpc_port=443)
        assert settings.host == "weaviate.example.com"
        assert settings.port == 443
        assert settings.grpc_port == 443