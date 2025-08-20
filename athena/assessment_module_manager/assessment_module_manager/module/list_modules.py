from typing import List

from .module import Module
from ..container import get_container


def list_modules() -> List[Module]:
    """Get a list of all Athena modules that are available."""
    return get_container().settings().list_modules()
