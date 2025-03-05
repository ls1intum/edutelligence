"""
Provides request metadata handling for Athena.

You can use this module to add metadata to HTTP responses for most endpoints (decorated with @with_meta).

Example usage:
    from fastapi import FastAPI
    from .metadata import MetaDataMiddleware, with_meta, emit_meta

    app = FastAPI()
    app.add_middleware(MetaDataMiddleware)

    @app.get("/items/{item_id}")
    @with_meta
    async def read_item(item_id: str):
        emit_meta("item_id", item_id)
        return {"item_id": item_id, "name": "Fancy Item"}

    Response of /items/42:
    {
        "data": {
            "item_id": 42
            "name": "Fancy Item"
        },
        "meta": {
            "item_id": 42
        }
    }
"""

import contextvars
from typing import Dict, Any
from functools import wraps

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


metadata_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("metadata")


class MetaDataMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle metadata in the context of HTTP requests.

    This middleware allows to set and get metadata context in each HTTP request.
    The context is then available throughout the processing of a request, even in asynchronous operations.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        """
        Middleware dispatcher.

        This method sets the metadata context at the start of processing each request.
        It then gets the response from the next middleware or the actual route handler, and returns it.

        Args:
            request (Request): The incoming HTTP request.
            call_next (RequestResponseEndpoint): The next middleware or route handler.

        Returns:
            The response from the next middleware or route handler.
        """
        metadata_context.set({})
        response = await call_next(request)
        return response


def get_meta() -> Dict[str, Any]:
    """
    Get the current metadata context.

    Returns:
        Dict[str, Any]: A dictionary with the current metadata context.
    """
    return metadata_context.get({})


def emit_meta(key: str, value: Any):
    """
    Add a key-value pair to the current metadata context for the current HTTP request.

    This metadata will be returned in the response of the HTTP request if the endpoint supports it.

    Args:
        key (str): The key for the metadata entry.
        value (Any): The value for the metadata entry.
    """
    metadata = metadata_context.get({})
    metadata[key] = value


def with_meta(func):
    """
    Decorator for endpoints that can send back metadata.
    
    Examples:
        >>> @app.post("/endpoint") 
        ... @with_meta
        ... def endpoint():
        ...    ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        data = await func(*args, **kwargs)
        return {
            "data": data,
            "meta": get_meta(),
        }
    return wrapper