from typing import List

from .module import Module
from ..settings import Settings


def list_modules() -> List[Module]:
    """Get a list of all Athena modules that are available."""
    settings = Settings()
    return settings.list_modules()
