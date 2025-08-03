"""
Tests for error handling in competency router.
"""

import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException

from atlasml.utils import handle_pipeline_error, validate_non_empty_string, safe_get_attribute
from atlasml.clients.weaviate import WeaviateConnectionError, WeaviateOperationError


def test_handle_pipeline_error_weaviate_connection():
    """Test handling of WeaviateConnectionError."""
    error = WeaviateConnectionError("Connection failed")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 503
    assert "Database connection error" in result.detail


def test_handle_pipeline_error_weaviate_operation():
    """Test handling of WeaviateOperationError."""
    error = WeaviateOperationError("Operation failed")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 500
    assert "Database operation failed" in result.detail


def test_handle_pipeline_error_value_error():
    """Test handling of ValueError."""
    error = ValueError("Invalid value")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 400
    assert "Invalid input" in result.detail


def test_handle_pipeline_error_key_error():
    """Test handling of KeyError."""
    error = KeyError("missing_field")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 400
    assert "Missing required field" in result.detail


def test_handle_pipeline_error_type_error():
    """Test handling of TypeError."""
    error = TypeError("Wrong type")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 400
    assert "Invalid data type" in result.detail


def test_handle_pipeline_error_memory_error():
    """Test handling of MemoryError."""
    error = MemoryError("Out of memory")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 507
    assert "Insufficient memory" in result.detail


def test_handle_pipeline_error_timeout_error():
    """Test handling of TimeoutError."""
    error = TimeoutError("Request timed out")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 408
    assert "Request timed out" in result.detail


def test_handle_pipeline_error_generic_exception():
    """Test handling of generic exceptions."""
    error = Exception("Unknown error")
    result = handle_pipeline_error(error, "test_operation")
    
    assert isinstance(result, HTTPException)
    assert result.status_code == 500
    assert "unexpected error occurred" in result.detail


def test_validate_non_empty_string_valid():
    """Test validation of valid non-empty strings."""
    result = validate_non_empty_string("valid string", "test_field")
    assert result == "valid string"
    
    # Test with whitespace that gets trimmed
    result = validate_non_empty_string("  valid string  ", "test_field")
    assert result == "valid string"


def test_validate_non_empty_string_empty():
    """Test validation of empty strings."""
    with pytest.raises(ValueError, match="test_field cannot be empty"):
        validate_non_empty_string("", "test_field")
    
    with pytest.raises(ValueError, match="test_field must be a string"):
        validate_non_empty_string(None, "test_field")


def test_validate_non_empty_string_whitespace_only():
    """Test validation of whitespace-only strings."""
    with pytest.raises(ValueError, match="test_field cannot be empty or contain only whitespace"):
        validate_non_empty_string("   ", "test_field")
    
    with pytest.raises(ValueError, match="test_field cannot be empty or contain only whitespace"):
        validate_non_empty_string("\t\n", "test_field")


def test_validate_non_empty_string_non_string():
    """Test validation of non-string values."""
    with pytest.raises(ValueError, match="test_field must be a string"):
        validate_non_empty_string(123, "test_field")
    
    with pytest.raises(ValueError, match="test_field must be a string"):
        validate_non_empty_string([], "test_field")


def test_safe_get_attribute_exists():
    """Test safe attribute access when attribute exists."""
    mock_obj = Mock()
    mock_obj.test_attr = "test_value"
    
    result = safe_get_attribute(mock_obj, "test_attr")
    assert result == "test_value"


def test_safe_get_attribute_missing():
    """Test safe attribute access when attribute is missing."""
    mock_obj = Mock(spec=[])  # Empty spec means no attributes
    
    result = safe_get_attribute(mock_obj, "missing_attr")
    assert result == "Unknown"
    
    result = safe_get_attribute(mock_obj, "missing_attr", "custom_default")
    assert result == "custom_default"


def test_safe_get_attribute_exception():
    """Test safe attribute access when getattr raises an exception."""
    
    class ExceptionRaisingObj:
        def __getattribute__(self, name):
            if name == "test_attr":
                raise ZeroDivisionError("Test exception")
            return super().__getattribute__(name)
    
    result = safe_get_attribute(ExceptionRaisingObj(), "test_attr")
    assert result == "Unknown"