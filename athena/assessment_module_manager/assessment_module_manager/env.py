"""Common place for environment variables with sensible defaults for local development."""
import os

from .module.list_modules import list_modules

PRODUCTION = os.environ.get("PRODUCTION", "0") == "1"

MODULE_SECRETS = {}
for module in list_modules():
    secret = os.environ.get(f"{module.name.upper()}_SECRET")
    if secret is None and PRODUCTION:
        raise ValueError(f"Missing secret for module {module.name}. "
                         f"Set the {module.name.upper()}_SECRET environment variable.")
    MODULE_SECRETS[module.name] = secret
