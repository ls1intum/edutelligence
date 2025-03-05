from typing import List

from assessment_module_manager.app import app
from assessment_module_manager.module import Module, list_modules


@app.get("/modules")
def get_modules() -> List[Module]:
    """
    Get a list of all Athena modules that are available.

    This endpoint is not authenticated.
    """
    return list_modules()
