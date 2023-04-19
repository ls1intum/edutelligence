import httpx
from fastapi import HTTPException
from httpx import Response

from .module import Module


async def request_to_module(module: Module, path: str, data: dict) -> Response:
    """
    Helper function to send a request to a module.
    It raises appropriate FastAPI HTTPException if the request fails.
    """
    try:
        async with httpx.AsyncClient(base_url=module.url) as client:
            response = await client.post(path, json=data)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Module {module.name} is not available")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response
