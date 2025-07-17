from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from app.creation_steps.models import Metadata, Repository


class ArtifactType(str, Enum):
    """Artifact type enumeration."""

    PROBLEM_STATEMENT = "PROBLEM_STATEMENT"
    TEMPLATE_REPOSITORY = "TEMPLATE_REPOSITORY"
    SOLUTION_REPOSITORY = "SOLUTION_REPOSITORY"
    TEST_REPOSITORY = "TEST_REPOSITORY"


class ArtifactLocation(BaseModel):
    """Location information for artifacts."""

    type: ArtifactType = Field(..., description="Type of artifact")
    file_path: Optional[str] = Field(
        None, description="Path in the repository, empty for problem statement"
    )
    start_line: Optional[int] = Field(None, description="Start line in the content")
    end_line: Optional[int] = Field(None, description="End line in the content")
    description: Optional[str] = Field(
        None, description="Optional description of the location"
    )


class ConsistencyIssueSeverity(str, Enum):
    """Severity levels for consistency issues."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConsistencyIssueType(str, Enum):
    """Type categories for consistency issues."""

    STRUCTURAL = "STRUCTURAL"
    SEMANTIC = "SEMANTIC"
    ASSESSMENT = "ASSESSMENT"
    PEDAGOGICAL = "PEDAGOGICAL"


class ConsistencyIssueCategory(str, Enum):
    """Specific categories for consistency issues."""

    # STRUCTURAL Issues
    METHOD_SIGNATURE_MISMATCH = "METHOD_SIGNATURE_MISMATCH"
    CONSTRUCTOR_SIGNATURE_MISMATCH = "CONSTRUCTOR_SIGNATURE_MISMATCH"
    INTERFACE_IMPLEMENTATION_CONFLICT = "INTERFACE_IMPLEMENTATION_CONFLICT"
    TYPE_DECLARATION_CONFLICT = "TYPE_DECLARATION_CONFLICT"
    INHERITANCE_HIERARCHY_MISMATCH = "INHERITANCE_HIERARCHY_MISMATCH"
    PACKAGE_STRUCTURE_MISMATCH = "PACKAGE_STRUCTURE_MISMATCH"
    MISSING_REQUIRED_ELEMENT = "MISSING_REQUIRED_ELEMENT"

    # SEMANTIC Issues
    NAMING_INCONSISTENCY = "NAMING_INCONSISTENCY"
    UML_TEXT_DEVIATION = "UML_TEXT_DEVIATION"
    EXAMPLE_CONTRADICTION = "EXAMPLE_CONTRADICTION"
    SPECIFICATION_AMBIGUITY = "SPECIFICATION_AMBIGUITY"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    REQUIREMENT_GAP = "REQUIREMENT_GAP"

    # ASSESSMENT Issues
    TEST_OBJECTIVE_MISMATCH = "TEST_OBJECTIVE_MISMATCH"
    TEST_COVERAGE_INCOMPLETE = "TEST_COVERAGE_INCOMPLETE"
    TEST_DATA_INCONSISTENT = "TEST_DATA_INCONSISTENT"
    GRADING_CRITERIA_CONFLICT = "GRADING_CRITERIA_CONFLICT"
    TEST_METHOD_NAMING_CONFLICT = "TEST_METHOD_NAMING_CONFLICT"

    # PEDAGOGICAL Issues
    COGNITIVE_LEVEL_MISMATCH = "COGNITIVE_LEVEL_MISMATCH"
    SCAFFOLDING_DISCONTINUITY = "SCAFFOLDING_DISCONTINUITY"
    PREREQUISITE_ASSUMPTION_VIOLATION = "PREREQUISITE_ASSUMPTION_VIOLATION"
    LEARNING_OBJECTIVE_CONTRADICTION = "LEARNING_OBJECTIVE_CONTRADICTION"
    COMPLEXITY_PROGRESSION_VIOLATION = "COMPLEXITY_PROGRESSION_VIOLATION"
    SKILL_TRANSFER_IMPEDIMENT = "SKILL_TRANSFER_IMPEDIMENT"


class ConsistencyIssue(BaseModel):
    """Represents a consistency issue found during review."""

    description: str = Field(..., description="Description of the consistency issue")
    severity: ConsistencyIssueSeverity = Field(
        ..., description="Severity level of the issue"
    )
    type: ConsistencyIssueType = Field(..., description="Type category of the issue")
    category: ConsistencyIssueCategory = Field(
        ..., description="Specific category of the issue"
    )
    primary_location: ArtifactLocation = Field(
        ..., description="Primary location where issue was detected"
    )
    related_locations: List[ArtifactLocation] = Field(
        default_factory=list, description="Related locations across artifacts"
    )
    suggested_fix: Optional[str] = Field(
        None, description="Simple suggested fix as a string"
    )


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
    issue_categories: Optional[List[ConsistencyIssueCategory]] = Field(
        None, description="Specify issue categories to check (leave empty for all)"
    )


class ConsistencyCheckResponse(BaseModel):
    """Response model for consistency check"""

    issues: List[ConsistencyIssue] = Field(
        ..., description="List of consistency issues found"
    )
    metadata: Metadata = Field(..., description="Response metadata")
