import configparser

from typing import List
from pathlib import Path

from .deployment import Deployment


def list_deployments() -> List[Deployment]:
    """Get a list of all Artemis instances that Athena should support."""
    deployments_config = configparser.ConfigParser()
    deployments_config.read(Path(__file__).parent.parent.parent / "deployments.ini")
    return [
        Deployment(
            name=deployment,
            url=deployments_config[deployment]["url"]
        )
        for deployment in deployments_config.sections()
    ]
