import json
from typing import TypeVar, Generic, Optional

import httpx
from fastapi import HTTPException

from assessment_module_manager.settings import Settings

from .module import Module
from ..module_registry import ModuleRegistry
from athena import ExerciseType
from assessment_module_manager.logger import logger
from pydantic import BaseModel

D = TypeVar('D')
M = TypeVar('M')
class ModuleResponse(BaseModel, Generic[D, M]):
    """
    A response from a module.
    """

    module_name: str
    status: int
    data: D
    meta: M


async def find_module_by_name(
    module_name: str, registry: ModuleRegistry
) -> Optional[Module]:
    """
    Helper function to find a module by name.
    """
    return registry.find_module_by_name(module_name)


# pylint: disable=too-many-positional-arguments
async def request_to_module(
    module: Module,
    headers: dict,
    path: str,
    lms_url: str,
    data: Optional[dict],
    method: str,
    settings: Settings,
) -> ModuleResponse:
    """
    Helper function to send a request to a module.
    It raises appropriate FastAPI HTTPException if the request fails.
    """
    module_secret = settings.module_secrets[module.name]
    if module_secret:
        headers["Authorization"] = module_secret  # for inter-Athena communication

    if module.type == ExerciseType.programming:
        # We need the Athena secret with the LMS to access repositories.
        # In order to only have to configure it once for the whole of Athena,
        # we pass it to the module from here.
        headers["X-Repository-Authorization-Secret"] = settings.deployment_secrets.get(
            lms_url, ""
        )
        # for repository access
        # should be the same as the LMS key

    try:
        async with httpx.AsyncClient(base_url=str(module.url), timeout=600) as client:
            if method == "POST":
                response = await client.post(path, json=data, headers=headers)
            elif method == "GET":
                response = await client.get(path, headers=headers)
            else:
                raise NotImplementedError(f"Method {method} is not implemented")
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503, detail=f"Module {module.name} is not available"
        ) from exc

    try:
        response_data = response.json()
        meta = response_data.get("meta", {})
        response_data = response_data.get("data", response_data)
    except json.JSONDecodeError:
        response_data = response.text
        meta = None
        logger.warning(
            "Module %s returned non-JSON response: %s", module.name, response.text
        )

    return ModuleResponse(module_name=module.name, status=response.status_code, data=response_data, meta=meta)
