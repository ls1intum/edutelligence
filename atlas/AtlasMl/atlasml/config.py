import os
import logging
from pydantic import BaseModel
from dotenv import load_dotenv

# Load from .env file
load_dotenv()



logger = logging.getLogger(__name__)


class APIKeyConfig(BaseModel):
    token: str


class WeaviateSettings(BaseModel):
    host: str
    port: int
    grpc_port: int


class AgentSettings(BaseModel):
    openai_api_key: str
    azure_endpoint: str
    azure_api_version: str
    atlas_api_url: str
    atlas_api_token: str
    artemis_api_url: str
    artemis_api_token: str


class Settings(BaseModel):
    api_keys: list[APIKeyConfig]
    weaviate: WeaviateSettings
    agent: AgentSettings
    sentry_dsn: str | None = None
    env: str = "dev"

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
        default_agent = AgentSettings(
            openai_api_key="default-test-key",
            azure_endpoint="https://default.openai.azure.com/",
            azure_api_version="2025-01-01-preview",
            atlas_api_url="http://localhost:8001",
            atlas_api_token="default-test-token",
            artemis_api_url="http://localhost:8080",
            artemis_api_token="default-test-token"
        )

        return cls(api_keys=default_api_keys, weaviate=default_weaviate, agent=default_agent, sentry_dsn=None, env="dev")

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

        # Get Sentry DSN from environment (optional)
        sentry_dsn = os.environ.get("SENTRY_DSN")
        
        # Get environment
        env = os.environ.get("ENV", "dev")

        # Get Agent settings from environment variables
        agent_settings = AgentSettings(
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            azure_endpoint=os.environ.get("AZURE_ENDPOINT", ""),
            azure_api_version=os.environ.get("AZURE_API_VERSION", "2025-01-01-preview"),
            atlas_api_url=os.environ.get("ATLAS_API_URL", "http://localhost:8001"),
            atlas_api_token=os.environ.get("ATLAS_API_TOKEN", ""),
            artemis_api_url=os.environ.get("ARTEMIS_API_URL", "http://localhost:8080"),
            artemis_api_token=os.environ.get("ARTEMIS_API_TOKEN", "")
        )

        logger.info(
            f"Loaded settings - ENV: {env}, API keys count: {len(api_keys)}, Weaviate: {weaviate_host}:{weaviate_port}, Sentry: {'configured' if sentry_dsn else 'not configured'}"
        )

        return cls(api_keys=api_keys, weaviate=weaviate_settings, agent=agent_settings, sentry_dsn=sentry_dsn, env=env)

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

    @property
    def sentry_dsn(self):
        return get_settings().sentry_dsn
    
    @property
    def env(self):
        return get_settings().env

    @property
    def agent(self):
        return get_settings().agent


settings = SettingsProxy()


# Backward compatibility class for AgentConfig
class AgentConfig:
    @property
    def OPENAI_API_KEY(self):
        return get_settings().agent.openai_api_key

    @property
    def AZURE_ENDPOINT(self):
        return get_settings().agent.azure_endpoint

    @property
    def AZURE_API_VERSION(self):
        return get_settings().agent.azure_api_version

    @property
    def ATLAS_API_URL(self):
        return get_settings().agent.atlas_api_url

    @property
    def ATLAS_API_TOKEN(self):
        return get_settings().agent.atlas_api_token

    @property
    def ARTEMIS_API_URL(self):
        return get_settings().agent.artemis_api_url

    @property
    def ARTEMIS_API_TOKEN(self):
        return get_settings().agent.artemis_api_token


# Create a singleton instance for backward compatibility
agent_config = AgentConfig()
