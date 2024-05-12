import configparser

from typing import List, cast
from pathlib import Path

from pydantic import AnyHttpUrl

from ..schemas.deployment import Deployment


def list_deployments() -> List[Deployment]:
    """Get a list of all Artemis instances that Athena should support."""
    deployments_config = configparser.ConfigParser()
    deployments_config.read(Path(__file__).parent.parent.parent / "deployments.ini")
    return [
        Deployment(
            name=deployment,
            url=cast(AnyHttpUrl, deployments_config[deployment]["url"]),
            artemis_id=deployments_config[deployment]["artemis_id"]
        )
        for deployment in deployments_config.sections()
    ]
