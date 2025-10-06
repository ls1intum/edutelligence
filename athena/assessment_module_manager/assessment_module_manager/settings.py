import os
import configparser
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings

from .logger import logger


class Settings(BaseSettings):
    production: bool = False

    module_secrets: dict[str, str | None] = {}
    deployment_secrets: dict[str, str] = {}

    def __init__(self, **values):
        # Map PRODUCTION environment variable to production field
        if "production" not in values:
            values["production"] = os.environ.get("PRODUCTION", "0") == "1"

        super().__init__(**values)

    def initialize_secrets(self, modules: List):
        """Initialize module and deployment secrets"""
        self.module_secrets = {}
        for module in modules:
            secret = os.environ.get(f"{module.name.upper()}_SECRET")
            if secret is None and self.production:
                raise ValueError(
                    f"Missing secret for module {module.name}. "
                    f"Set the {module.name.upper()}_SECRET environment variable."
                )
            self.module_secrets[module.name] = secret

        self.deployment_secrets = {}
        for deployment in self.list_deployments():
            secret = os.environ.get(f"LMS_{deployment.name.upper()}_SECRET")
            if secret is None and self.production:
                raise ValueError(
                    "Missing secret for LMS deployment %s. "
                    "Set the LMS_%s_SECRET environment variable to secure the communication "
                    "between the LMS and the assessment module manager."
                    % (deployment.name, deployment.name.upper())
                )
            if secret is None and not self.production:
                secret = "abcdef12345"  # noqa: This secret is only used for development setups for simplicity
            self.deployment_secrets[deployment.url] = secret or ""

    def list_deployments(self) -> list:
        """Get a list of all LMS instances that Athena should support."""
        from .deployment.deployment import Deployment

        deployments_config = configparser.ConfigParser()
        deployments_config.read(Path(__file__).parent.parent / "deployments.ini")
        return [
            Deployment(name=deployment, url=deployments_config[deployment]["url"])
            for deployment in deployments_config.sections()
        ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
