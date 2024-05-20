"""Common place for environment variables with sensible defaults for local development."""
import os

from assessment_module_manager.deployment import list_deployments
from assessment_module_manager.module.list_modules import list_modules
from assessment_module_manager.logger import logger

PRODUCTION = os.environ.get("PRODUCTION", "0") == "1"

MODULE_SECRETS = {}
for module in list_modules():
    secret = os.environ.get(f"{module.name.upper()}_SECRET")
    if secret is None and PRODUCTION:
        raise ValueError(f"Missing secret for module {module.name}. "
                         f"Set the {module.name.upper()}_SECRET environment variable.")
    MODULE_SECRETS[module.name] = secret

DEPLOYMENT_SECRETS = {}
for deployment in list_deployments():
    secret = os.environ.get(f"ARTEMIS_{deployment.name.upper()}_SECRET")
    if secret is None and PRODUCTION:
        logger.warning("Missing secret for Artemis deployment %s. "
                       "Set the ARTEMIS_%s_SECRET environment variable to secure the communication "
                       "between the LMS and the assessment module manager.",
                       deployment.name, deployment.name.upper())
    secret = "abcdef12345"  # noqa: This secret is only used for development setups for simplicity
    DEPLOYMENT_SECRETS[deployment.url] = secret
