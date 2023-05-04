import json
from typing import TypeVar, Generic

import httpx
from fastapi import HTTPException
from pydantic.generics import GenericModel

from . import AvailableModuleNames, list_modules
from .module import Module

T = TypeVar('T')
class ModuleResponse(GenericModel, Generic[T]):
    """
    A response from a module.
    """
    module_name: str
    status: int
    data: T


async def find_module_by_name(module_name: AvailableModuleNames) -> Module:
    """
    Helper function to find a module by name.
    """
    for module in list_modules():
        if module.name == module_name:
            return module


async def request_to_module(module: Module, path: str, data: dict) -> ModuleResponse:
    """
    Helper function to send a request to a module.
    It raises appropriate FastAPI HTTPException if the request fails.
    """
    try:
        async with httpx.AsyncClient(base_url=module.url, timeout=600) as client:
            response = await client.post(path, json=data)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Module {module.name} is not available")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            response_data = response.text
        raise HTTPException(
            status_code=response.status_code,
            detail=ModuleResponse(module_name=module.name, status=response.status_code, data=response_data).dict(),
        )
    return ModuleResponse(module_name=module.name, status=response.status_code, data=response.json())
