from typing import List
from fastapi import APIRouter, Depends

from assessment_module_manager.module import Module
from ..dependencies import get_registry
from ..module_registry import ModuleRegistry

router = APIRouter()


@router.get("/modules")
def get_modules(
    registry: ModuleRegistry = Depends(get_registry),
) -> List[Module]:
    """
    Get a list of all Athena modules that are available.

    This endpoint is not authenticated.
    """
    return registry.get_all_modules()
