"""Common place for environment variables with sensible defaults for local development."""
import os

from athena.helpers.list_deployments import list_deployments

PRODUCTION = os.environ.get("PRODUCTION", "0") == "1"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///../data/data.sqlite")

DEPLOYMENT_SECRETS = {}
for deployment in list_deployments():
    secret = os.environ.get(f"{deployment.name.upper()}_SECRET")
    if secret is None and PRODUCTION:
        raise ValueError(f"Missing secret for Artemis deployment {deployment.name}. "
                         f"Set the {deployment.name.upper()}_SECRET environment variable.")
    DEPLOYMENT_SECRETS[deployment.name] = secret
