"""Shared exceptions for all creation steps."""

from typing import List, Optional, Dict, Any


class CreationStepException(Exception):
    """Base exception for all creation step errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class WorkspaceException(CreationStepException):
    """Exception raised for workspace-related errors."""
    pass


class FileSystemException(CreationStepException):
    """Exception raised for file system operations."""
    
    def __init__(self, message: str, file_path: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.file_path = file_path


class GitException(CreationStepException):
    """Exception raised for Git operations."""
    pass


class ValidationException(CreationStepException):
    """Exception raised for validation errors."""
    pass


class ConfigurationException(CreationStepException):
    """Exception raised for configuration errors."""
    pass 