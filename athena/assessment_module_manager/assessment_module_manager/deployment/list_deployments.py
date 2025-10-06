from typing import List

from .deployment import Deployment
from ..settings import Settings


def list_deployments() -> List[Deployment]:
    """Get a list of all LMS instances that Athena should support."""
    settings = Settings()
    return settings.list_deployments()
