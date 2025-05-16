"""Utility functions for working with gRPC and Pydantic models."""

import logging
from typing import TypeVar, Type, Callable
from app.grpc.models import GrpcMessage
from functools import wraps

# Generic type for Pydantic models (GrpcMessage is a subclass of BaseModel)
T = TypeVar("T", bound=GrpcMessage)


def validate_grpc_request(model_class: Type[T]) -> Callable:
    """
    Decorator for gRPC servicer methods that validates and converts gRPC request to Pydantic model.

    Args:
        model_class: The Pydantic model class to use for validation

    Returns:
        A decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, request, context, *args, **kwargs):
            try:
                # Convert gRPC request to Pydantic model
                pydantic_request = model_class.from_grpc(request)

                # Call the original method with the validated model
                return await func(self, pydantic_request, context, *args, **kwargs)
            except Exception as e:
                logging.error(f"Error validating gRPC request: {str(e)}")
                # Handle the error appropriately
                raise e

        return wrapper

    return decorator
