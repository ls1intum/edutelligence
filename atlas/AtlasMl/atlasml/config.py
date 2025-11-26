"""
Configuration models and environment loading for AtlasML.

This module defines strongly-typed settings using Pydantic `BaseModel`s and a
loader that reads from environment variables. It also provides a proxy for
convenient access within the application.

Environment variables:
- ATLAS_API_KEYS: Comma-separated list of API key tokens used for request auth
- WEAVIATE_HOST: Weaviate host (e.g., "localhost")
- WEAVIATE_PORT: Weaviate REST port (e.g., 8080)
- WEAVIATE_GRPC_PORT: Weaviate gRPC port (e.g., 50051)
- SENTRY_DSN: Optional Sentry DSN used only in production
- ENV: Environment name (e.g., "dev", "production")

Defaults are provided automatically in test environments or when explicitly
requested via `get_settings(use_defaults=True)`.
"""

import os
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class APIKeyConfig(BaseModel):
    """Single API key token definition used for header-based authentication."""
    token: str


class WeaviateSettings(BaseModel):
    """Connection parameters for the Weaviate vector database."""
    host: str
    port: int
    grpc_port: int


class Settings(BaseModel):
    """Top-level application settings used across AtlasML services.

    Attributes:
        api_keys: Allowed API keys for authenticating requests
        weaviate: Weaviate connection settings
        sentry_dsn: Optional Sentry DSN (used when `env` is production)
        env: Current environment label (e.g., dev, production)
    """
    api_keys: list[APIKeyConfig]
    weaviate: WeaviateSettings
    sentry_dsn: str | None = None
    env: str = "dev"

    @classmethod
    def _get_default_settings(cls):
        """Construct safe defaults for development and tests.

        The defaults are intentionally conservative, enabling a local Weaviate
        connection on common ports and a single test API key.
        """
        logger.warning(
            "Using default settings - ensure environment variables are set for production"
        )

        default_api_keys = [APIKeyConfig(token="default-test-token")]
        default_weaviate = WeaviateSettings(
            host="localhost", port=8080, grpc_port=50051
        )

        return cls(api_keys=default_api_keys, weaviate=default_weaviate, sentry_dsn=None, env="dev")

    @classmethod
    def get_settings(cls, use_defaults: bool = False):
        """Load settings from environment variables or provide defaults.

        Args:
            use_defaults: If True, bypass environment validation and return
                default settings suitable for local development/tests.
        """
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

        # Get Sentry DSN from environment (optional)
        sentry_dsn = os.environ.get("SENTRY_DSN")
        
        # Get environment
        env = os.environ.get("ENV", "dev")

        logger.info(
            f"Loaded settings - ENV: {env}, API keys count: {len(api_keys)}, Weaviate: {weaviate_host}:{weaviate_port}, Sentry: {'configured' if sentry_dsn else 'not configured'}"
        )

        return cls(api_keys=api_keys, weaviate=weaviate_settings, sentry_dsn=sentry_dsn, env=env)

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
    """Lazy proxy to access resolved settings without re-parsing env vars."""
    @property
    def api_keys(self):
        return get_settings().api_keys

    @property
    def weaviate(self):
        return get_settings().weaviate

    @property
    def sentry_dsn(self):
        return get_settings().sentry_dsn
    
    @property
    def env(self):
        return get_settings().env


settings = SettingsProxy()
