from typing import List
from fastapi import APIRouter, Depends

from assessment_module_manager.module import Module
from ..dependencies import get_settings
from ..settings import Settings

router = APIRouter()


@router.get("/modules")
def get_modules(
    settings: Settings = Depends(get_settings),
) -> List[Module]:
    """
    Get a list of all Athena modules that are available.

    This endpoint is not authenticated.
    """
    return settings.list_modules()
