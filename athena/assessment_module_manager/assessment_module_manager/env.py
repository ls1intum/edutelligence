"""Common place for environment variables with sensible defaults for local development."""
import os

from assessment_module_manager.deployment import list_deployments
from assessment_module_manager.module.list_modules import list_modules

PRODUCTION = os.environ.get("PRODUCTION", "0") == "1"
SECRET = os.getenv("SECRET")  # Artemis <-> Athena
if SECRET is None:
    if PRODUCTION == "1":
        raise ValueError("Missing SECRET environment variable. "
                         "Set it to a random string to secure the communication between the LMS and the assessment module manager.")
    SECRET = "abcdef12345"  # noqa: This secret is only used for development setups for simplicity

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
        raise ValueError(f"Missing secret for Artemis deployment {deployment.name}. "
                         f"Set the {deployment.name.upper()}_SECRET environment variable.")
    DEPLOYMENT_SECRETS[deployment.url] = secret
