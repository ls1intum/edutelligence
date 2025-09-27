from typing import List

from .module import Module
from ..module_registry import ModuleRegistry


def list_modules(registry: ModuleRegistry) -> List[Module]:
    """Get a list of all Athena modules that are available."""
    return registry.get_all_modules()
