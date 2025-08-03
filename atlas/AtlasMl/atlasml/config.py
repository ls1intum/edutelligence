import os
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class APIKeyConfig(BaseModel):
    token: str


class WeaviateSettings(BaseModel):
    host: str
    port: int
    grpc_port: int


class Settings(BaseModel):
    api_keys: list[APIKeyConfig]
    weaviate: WeaviateSettings

    @classmethod
    def _get_default_settings(cls):
        """Get default settings for testing and development."""
        logger.warning(
            "Using default settings - ensure environment variables are set for production"
        )

        default_api_keys = [APIKeyConfig(token="default-test-token")]
        default_weaviate = WeaviateSettings(
            host="localhost", port=8080, grpc_port=50051
        )

        return cls(api_keys=default_api_keys, weaviate=default_weaviate)

    @classmethod
    def get_settings(cls, use_defaults: bool = False):
        """Get the settings from environment variables with optional defaults."""
        logger.info("Loading settings from environment variables")

        # Check if we should use defaults (for testing)
        if use_defaults:
            return cls._get_default_settings()

        # Check for required environment variables
        required_vars = [
            "ATLAS_API_KEYS",
            "WEAVIATE_HOST",
            "WEAVIATE_PORT",
            "WEAVIATE_GRPC_PORT",
        ]
        missing_vars = [var for var in required_vars if not os.environ.get(var)]

        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}. Set use_defaults=True for testing."
            logger.error(error_msg)
            if "PYTEST_CURRENT_TEST" in os.environ or "TEST" in os.environ.get(
                "ENV", ""
            ):
                logger.warning("Test environment detected, using default settings")
                return cls._get_default_settings()
            raise ValueError(error_msg)

        # Get API keys from environment variable (comma-separated)
        api_keys_str = os.environ.get("ATLAS_API_KEYS")
        api_keys = [
            APIKeyConfig(token=token.strip())
            for token in api_keys_str.split(",")
            if token.strip()
        ]

        if not api_keys:
            raise ValueError("ATLAS_API_KEYS must contain at least one valid API key")

        # Get Weaviate settings from environment variables with validation
        try:
            weaviate_host = os.environ.get("WEAVIATE_HOST")
            weaviate_port = int(os.environ.get("WEAVIATE_PORT"))
            weaviate_grpc_port = int(os.environ.get("WEAVIATE_GRPC_PORT"))
        except ValueError as e:
            raise ValueError(f"Invalid port configuration: {e}") from e

        weaviate_settings = WeaviateSettings(
            host=weaviate_host, port=weaviate_port, grpc_port=weaviate_grpc_port
        )

        logger.info(
            f"Loaded settings - API keys count: {len(api_keys)}, Weaviate: {weaviate_host}:{weaviate_port}"
        )

        return cls(api_keys=api_keys, weaviate=weaviate_settings)

    @classmethod
    def get_api_keys(cls):
        logger.debug(f"Getting API keys: {cls.get_settings().api_keys}")
        return cls.get_settings().api_keys


# Lazy initialization of settings - will be created when first accessed
_settings = None


def get_settings(use_defaults: bool = None) -> Settings:
    """Get the global settings instance, creating it if necessary."""
    global _settings
    if _settings is None:
        # Auto-detect test environment if not specified
        if use_defaults is None:
            use_defaults = (
                "PYTEST_CURRENT_TEST" in os.environ
                or "TEST" in os.environ.get("ENV", "")
                or os.environ.get("TESTING", "").lower() == "true"
            )
        _settings = Settings.get_settings(use_defaults=use_defaults)
    return _settings


def reset_settings():
    """Reset the global settings instance. Useful for testing."""
    global _settings
    _settings = None


# For backward compatibility, create a property-like access
class SettingsProxy:
    @property
    def api_keys(self):
        return get_settings().api_keys

    @property
    def weaviate(self):
        return get_settings().weaviate


settings = SettingsProxy()
