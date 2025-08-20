from typing import List

from .deployment import Deployment
from ..container import get_container


def list_deployments() -> List[Deployment]:
    """Get a list of all LMS instances that Athena should support."""
    return get_container().settings().list_deployments()
