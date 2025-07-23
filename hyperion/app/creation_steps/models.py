"""
Shared Pydantic models for all creation steps.

This module contains common models used across multiple creation steps.
"""

from typing import List
from pydantic import BaseModel, Field


class RepositoryFile(BaseModel):
    """Represents a file in a repository with content."""

    path: str = Field(..., description="File path relative to the repository root")
    content: str = Field(..., description="File content")


class Repository(BaseModel):
    """Represents a collection of files that form a repository."""

    files: List[RepositoryFile] = Field(
        ..., description="Files contained in the repository"
    )


class Metadata(BaseModel):
    """Metadata for requests and responses."""

    trace_id: str = Field(..., description="UUID with LLM trace ID")
