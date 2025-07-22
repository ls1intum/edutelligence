from enum import Enum
from typing import List
from pydantic import BaseModel, Field

from app.creation_steps.models import Metadata, Repository


class ArtifactType(str, Enum):
    """Artifact type enumeration."""

    PROBLEM_STATEMENT = "PROBLEM_STATEMENT"
    TEMPLATE_REPOSITORY = "TEMPLATE_REPOSITORY"

    # Ignored for now
    # SOLUTION_REPOSITORY = "SOLUTION_REPOSITORY"
    # TEST_REPOSITORY = "TEST_REPOSITORY"


class ArtifactLocation(BaseModel):
    """Location information for artifacts."""

    type: ArtifactType = Field(..., description="Type of artifact")
    file_path: str = Field(
        description="Path to file, empty or problem_statement.md for problem statement"
    )
    start_line: int = Field(description="Start line number (1-based)")
    end_line: int = Field(description="End line number (1-based)")


class ConsistencyIssueSeverity(str, Enum):
    """Severity levels for consistency issues."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# Base classes for consistency issues and results
class ConsistencyIssue(BaseModel):
    """Base class for consistency issues. Do not use directly, use subclasses instead."""

    description: str = Field(description="Clear explanation of the consistency issue")
    severity: ConsistencyIssueSeverity = Field(
        description="Student impact severity level"
    )
    category: str = Field(description="Specific category of consistency issue")
    related_locations: List[ArtifactLocation] = Field(
        description="Related locations across artifacts"
    )
    suggested_fix: str = Field(description="Actionable correction to resolve the issue")


class ConsistencyResult(BaseModel):
    """Base class for consistency check results. Do not use directly, use subclasses instead."""

    issues: List[ConsistencyIssue] = Field(
        description="List of consistency issues found"
    )


# Supported structural consistency sub-categories
class StructuralConsistencyIssueCategory(str, Enum):
    """Structural consistency issue sub-categories"""

    # Method return type, parameters, or visibility differs between artifacts
    METHOD_RETURN_TYPE_MISMATCH = "METHOD_RETURN_TYPE_MISMATCH"

    # Method parameters differ between specification and template
    METHOD_PARAMETER_MISMATCH = "METHOD_PARAMETER_MISMATCH"

    # Constructor parameters differ between specification and template
    CONSTRUCTOR_PARAMETER_MISMATCH = "CONSTRUCTOR_PARAMETER_MISMATCH"

    # Attribute data types inconsistent across artifacts
    ATTRIBUTE_TYPE_MISMATCH = "ATTRIBUTE_TYPE_MISMATCH"

    # Method/attribute visibility differs between specification and template
    VISIBILITY_MISMATCH = "VISIBILITY_MISMATCH"


# Supported semantic consistency sub-categories
class SemanticConsistencyIssueCategory(str, Enum):
    """Semantic consistency issue sub-categories"""

    # Same conceptual entity has different names across artifacts
    IDENTIFIER_NAMING_INCONSISTENCY = "IDENTIFIER_NAMING_INCONSISTENCY"


class ConsistencyCheckRequest(BaseModel):
    """Request model for consistency check"""

    problem_statement: str = Field(..., description="Problem statement to check")
    solution_repository: Repository = Field(
        ..., description="Solution repository to check"
    )
    template_repository: Repository = Field(
        ..., description="Template repository to check"
    )
    test_repository: Repository = Field(..., description="Test repository to check")


class ConsistencyCheckResponse(BaseModel):
    """Response model for consistency check"""

    issues: List[ConsistencyIssue] = Field(
        ..., description="List of consistency issues found"
    )
    metadata: Metadata = Field(..., description="Response metadata")
