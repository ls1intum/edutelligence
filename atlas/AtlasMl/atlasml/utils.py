"""
Utility functions for the AtlasML application.
"""

import logging
from fastapi import HTTPException, status
from typing import Any

from atlasml.clients.weaviate import WeaviateConnectionError, WeaviateOperationError

logger = logging.getLogger(__name__)


def handle_pipeline_error(error: Exception, operation: str) -> HTTPException:
    """
    Centralized error handling for pipeline operations.
    
    Args:
        error: The exception that occurred
        operation: Description of the operation that failed
        
    Returns:
        HTTPException with appropriate status code and message
    """
    if isinstance(error, WeaviateConnectionError):
        logger.error(f"Weaviate connection error in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection error. Please try again later."
        )
    elif isinstance(error, WeaviateOperationError):
        logger.error(f"Weaviate operation error in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed. Please try again later."
        )
    elif isinstance(error, ValueError):
        logger.error(f"Validation error in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid input: {str(error)}"
        )
    elif isinstance(error, KeyError):
        logger.error(f"Missing required data in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required field: {str(error)}"
        )
    elif isinstance(error, TypeError):
        logger.error(f"Type error in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid data type provided"
        )
    elif isinstance(error, MemoryError):
        logger.error(f"Memory error in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="Insufficient memory to process request. Please try with smaller data."
        )
    elif isinstance(error, TimeoutError):
        logger.error(f"Timeout error in {operation}: {error}")
        return HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Request timed out. Please try again later."
        )
    else:
        logger.error(f"Unexpected error in {operation}: {error}", exc_info=True)
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )


def validate_non_empty_string(value: Any, field_name: str) -> str:
    """
    Validate that a value is a non-empty string.
    
    Args:
        value: The value to validate
        field_name: Name of the field for error messages
        
    Returns:
        The validated string value
        
    Raises:
        ValueError: If the value is not a valid non-empty string
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    
    if not value.strip():
        raise ValueError(f"{field_name} cannot be empty or contain only whitespace")
    
    return value.strip()


def safe_get_attribute(obj: Any, attr_name: str, default: str = "Unknown") -> str:
    """
    Safely get an attribute from an object with a default fallback.
    
    Args:
        obj: The object to get the attribute from
        attr_name: Name of the attribute
        default: Default value if attribute doesn't exist
        
    Returns:
        The attribute value or default
    """
    try:
        return getattr(obj, attr_name, default)
    except Exception:
        return default