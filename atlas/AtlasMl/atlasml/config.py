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
    def _validate_required_env_vars(cls):
        """Validate that all required environment variables are set."""
        required_vars = ["ATLAS_API_KEYS", "WEAVIATE_HOST", "WEAVIATE_PORT", "WEAVIATE_GRPC_PORT"]
        missing_vars = []
        
        for var in required_vars:
            if not os.environ.get(var):
                missing_vars.append(var)
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    @classmethod
    def get_settings(cls):
        """Get the settings from environment variables."""
        logger.info("Loading settings from environment variables")
        
        # Validate all required environment variables exist
        cls._validate_required_env_vars()
        
        # Get API keys from environment variable (comma-separated)
        api_keys_str = os.environ.get("ATLAS_API_KEYS")
        api_keys = [APIKeyConfig(token=token.strip()) for token in api_keys_str.split(",") if token.strip()]
        
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
            host=weaviate_host,
            port=weaviate_port,
            grpc_port=weaviate_grpc_port
        )
        
        logger.info(f"Loaded settings - API keys count: {len(api_keys)}, Weaviate: {weaviate_host}:{weaviate_port}")
        
        return cls(api_keys=api_keys, weaviate=weaviate_settings)
        
    @classmethod
    def get_api_keys(cls):
        logger.debug(f"Getting API keys: {cls.get_settings().api_keys}")
        return cls.get_settings().api_keys

# Lazy initialization of settings - will be created when first accessed
_settings = None

def get_settings() -> Settings:
    """Get the global settings instance, creating it if necessary."""
    global _settings
    if _settings is None:
        _settings = Settings.get_settings()
    return _settings

# For backward compatibility, create a property-like access
class SettingsProxy:
    @property
    def api_keys(self):
        return get_settings().api_keys
    
    @property
    def weaviate(self):
        return get_settings().weaviate

settings = SettingsProxy()