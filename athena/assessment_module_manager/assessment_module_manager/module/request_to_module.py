import json
from typing import TypeVar, Generic

import httpx
from fastapi import HTTPException
from pydantic.generics import GenericModel

from athena import ExerciseTypeVar
from .module import Module
from .resolve_module import resolve_module

T = TypeVar('T')
class ModuleResponse(GenericModel, Generic[T]):
    """
    A response from a module.
    """
    module_name: str
    status: int
    data: T


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


async def request_to_module_by_exercise(exercise: ExerciseTypeVar, path: str, data: dict) -> ModuleResponse:
    """
    Helper function to send a request to a module by resolving the module from the exercise.
    It raises appropriate FastAPI HTTPException if the request fails or if no fitting module is found.
    """
    try:
        module = resolve_module(exercise)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"No module found for exercise {exercise.id} of type {exercise.type}")
    return await request_to_module(module, path, data)
