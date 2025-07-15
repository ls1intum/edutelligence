from typing import List
from enum import Enum
from pydantic import BaseModel, Field

from app.grpc.hyperion_pb2 import (
    ArtifactLocation,
    ArtifactType,
    ConsistencyIssue,
    ConsistencyIssueCategory,
    ConsistencyIssueSeverity,
    ConsistencyIssueType,
)


class SeverityEnum(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class StructuralConsistencyIssueCategory(str, Enum):
    METHOD_SIGNATURE_MISMATCH = "METHOD_SIGNATURE_MISMATCH"
    # Method return type, parameters, or visibility differs between artifacts
    CONSTRUCTOR_SIGNATURE_MISMATCH = "CONSTRUCTOR_SIGNATURE_MISMATCH"
    # Constructor parameters differ between specification and template
    INTERFACE_IMPLEMENTATION_CONFLICT = "INTERFACE_IMPLEMENTATION_CONFLICT"
    # Required interface cannot be implemented as specified
    TYPE_DECLARATION_CONFLICT = "TYPE_DECLARATION_CONFLICT"
    # Data types inconsistent across artifacts
    INHERITANCE_HIERARCHY_MISMATCH = "INHERITANCE_HIERARCHY_MISMATCH"
    # Extends/implements relationships differ between UML and template
    PACKAGE_STRUCTURE_MISMATCH = "PACKAGE_STRUCTURE_MISMATCH"
    # Import/package organization prevents compilation
    MISSING_REQUIRED_ELEMENT = "MISSING_REQUIRED_ELEMENT"
    # Essential class/method/attribute missing from template


class ArtifactTypeEnum(str, Enum):
    PROBLEM_STATEMENT = "PROBLEM_STATEMENT"
    TEMPLATE_REPOSITORY = "TEMPLATE_REPOSITORY"


class ArtifactLocationModel(BaseModel):
    type: ArtifactTypeEnum = Field(description="Type of artifact")
    file_path: str = Field(description="Path to file, empty for problem statement")
    start_line: int = Field(description="Start line number (1-based)")
    end_line: int = Field(description="End line number (1-based)")


# Do not use this directly, use subclasses instead
class ConsistencyIssueModel(BaseModel):
    description: str = Field(description="Clear explanation of the signature mismatch")
    severity: SeverityEnum = Field(description="Student impact severity level")
    category: str = Field(description="Specific category of consistency issue")
    primary_location: ArtifactLocationModel = Field(
        description="Primary location where issue was detected"
    )
    related_locations: List[ArtifactLocationModel] = Field(
        description="Related locations across artifacts"
    )
    suggested_fix: str = Field(
        description="Actionable correction to resolve the mismatch"
    )


class StructuralConsistencyIssueModel(ConsistencyIssueModel):
    """A signature consistency issue found between problem statement and template."""

    description: str = Field(description="Clear explanation of the signature mismatch")
    severity: SeverityEnum = Field(description="Student impact severity level")
    category: StructuralConsistencyIssueCategory = Field(
        description="Specific category of structural consistency issue"
    )
    primary_location: ArtifactLocationModel = Field(
        description="Primary location where issue was detected"
    )
    related_locations: List[ArtifactLocationModel] = Field(
        description="Related locations across artifacts"
    )
    suggested_fix: str = Field(
        description="Actionable correction to resolve the mismatch"
    )


# Do not use this directly, use subclasses instead
class ConsistencyResult(BaseModel):
    """Result of consistency issue analysis."""

    issues: List[ConsistencyIssueModel] = Field(
        description="List of detected consistency issues"
    )


class StructuralConsistencyResult(ConsistencyResult):
    """Result of structural consistency issue analysis."""

    issues: List[StructuralConsistencyIssueModel] = Field(
        description="List of detected structural consistency issues"
    )


# Without category similar as in TypeScript with Omit
def convert_consistency_issue_to_protobuf(
    issue: ConsistencyIssueModel,
) -> ConsistencyIssue:
    """Convert Pydantic model to protobuf ConsistencyIssue."""
    severity_map = {
        "LOW": ConsistencyIssueSeverity.LOW,
        "MEDIUM": ConsistencyIssueSeverity.MEDIUM,
        "HIGH": ConsistencyIssueSeverity.HIGH,
    }

    artifact_type_map = {
        "PROBLEM_STATEMENT": ArtifactType.PROBLEM_STATEMENT,
        "TEMPLATE_REPOSITORY": ArtifactType.TEMPLATE_REPOSITORY,
    }

    # Convert primary location
    primary_location = ArtifactLocation(
        type=artifact_type_map[issue.primary_location.type],
        file_path=issue.primary_location.file_path,
        start_line=issue.primary_location.start_line,
        end_line=issue.primary_location.end_line,
    )

    # Convert related locations
    related_locations = []
    for rel_loc in issue.related_locations:
        related_locations.append(
            ArtifactLocation(
                type=artifact_type_map[rel_loc.type],
                file_path=rel_loc.file_path,
                start_line=rel_loc.start_line,
                end_line=rel_loc.end_line,
            )
        )

    category_map = {
        "METHOD_SIGNATURE_MISMATCH": ConsistencyIssueCategory.METHOD_SIGNATURE_MISMATCH,
        "CONSTRUCTOR_SIGNATURE_MISMATCH": ConsistencyIssueCategory.CONSTRUCTOR_SIGNATURE_MISMATCH,
        "INTERFACE_IMPLEMENTATION_CONFLICT": ConsistencyIssueCategory.INTERFACE_IMPLEMENTATION_CONFLICT,
        "TYPE_DECLARATION_CONFLICT": ConsistencyIssueCategory.TYPE_DECLARATION_CONFLICT,
        "INHERITANCE_HIERARCHY_MISMATCH": ConsistencyIssueCategory.INHERITANCE_HIERARCHY_MISMATCH,
        "PACKAGE_STRUCTURE_MISMATCH": ConsistencyIssueCategory.PACKAGE_STRUCTURE_MISMATCH,
        "MISSING_REQUIRED_ELEMENT": ConsistencyIssueCategory.MISSING_REQUIRED_ELEMENT,
        "NAMING_INCONSISTENCY": ConsistencyIssueCategory.NAMING_INCONSISTENCY,
        "UML_TEXT_DEVIATION": ConsistencyIssueCategory.UML_TEXT_DEVIATION,
        "EXAMPLE_CONTRADICTION": ConsistencyIssueCategory.EXAMPLE_CONTRADICTION,
        "SPECIFICATION_AMBIGUITY": ConsistencyIssueCategory.SPECIFICATION_AMBIGUITY,
        "CONSTRAINT_VIOLATION": ConsistencyIssueCategory.CONSTRAINT_VIOLATION,
        "REQUIREMENT_GAP": ConsistencyIssueCategory.REQUIREMENT_GAP,
        "TEST_OBJECTIVE_MISMATCH": ConsistencyIssueCategory.TEST_OBJECTIVE_MISMATCH,
        "TEST_COVERAGE_INCOMPLETE": ConsistencyIssueCategory.TEST_COVERAGE_INCOMPLETE,
        "TEST_DATA_INCONSISTENT": ConsistencyIssueCategory.TEST_DATA_INCONSISTENT,
        "GRADING_CRITERIA_CONFLICT": ConsistencyIssueCategory.GRADING_CRITERIA_CONFLICT,
        "TEST_METHOD_NAMING_CONFLICT": ConsistencyIssueCategory.TEST_METHOD_NAMING_CONFLICT,
        "COGNITIVE_LEVEL_MISMATCH": ConsistencyIssueCategory.COGNITIVE_LEVEL_MISMATCH,
        "SCAFFOLDING_DISCONTINUITY": ConsistencyIssueCategory.SCAFFOLDING_DISCONTINUITY,
        "PREREQUISITE_ASSUMPTION_VIOLATION": ConsistencyIssueCategory.PREREQUISITE_ASSUMPTION_VIOLATION,
        "LEARNING_OBJECTIVE_CONTRADICTION": ConsistencyIssueCategory.LEARNING_OBJECTIVE_CONTRADICTION,
        "COMPLEXITY_PROGRESSION_VIOLATION": ConsistencyIssueCategory.COMPLEXITY_PROGRESSION_VIOLATION,
        "SKILL_TRANSFER_IMPEDIMENT": ConsistencyIssueCategory.SKILL_TRANSFER_IMPEDIMENT,
    }

    category_to_type_map = {
        "METHOD_SIGNATURE_MISMATCH": ConsistencyIssueType.STRUCTURAL,
        "CONSTRUCTOR_SIGNATURE_MISMATCH": ConsistencyIssueType.STRUCTURAL,
        "INTERFACE_IMPLEMENTATION_CONFLICT": ConsistencyIssueType.STRUCTURAL,
        "TYPE_DECLARATION_CONFLICT": ConsistencyIssueType.STRUCTURAL,
        "INHERITANCE_HIERARCHY_MISMATCH": ConsistencyIssueType.STRUCTURAL,
        "PACKAGE_STRUCTURE_MISMATCH": ConsistencyIssueType.STRUCTURAL,
        "MISSING_REQUIRED_ELEMENT": ConsistencyIssueType.STRUCTURAL,
        "NAMING_INCONSISTENCY": ConsistencyIssueType.SEMANTIC,
        "UML_TEXT_DEVIATION": ConsistencyIssueType.SEMANTIC,
        "EXAMPLE_CONTRADICTION": ConsistencyIssueType.SEMANTIC,
        "SPECIFICATION_AMBIGUITY": ConsistencyIssueType.SEMANTIC,
        "CONSTRAINT_VIOLATION": ConsistencyIssueType.SEMANTIC,
        "REQUIREMENT_GAP": ConsistencyIssueType.SEMANTIC,
        "TEST_OBJECTIVE_MISMATCH": ConsistencyIssueType.ASSESSMENT,
        "TEST_COVERAGE_INCOMPLETE": ConsistencyIssueType.ASSESSMENT,
        "TEST_DATA_INCONSISTENT": ConsistencyIssueType.ASSESSMENT,
        "GRADING_CRITERIA_CONFLICT": ConsistencyIssueType.ASSESSMENT,
        "TEST_METHOD_NAMING_CONFLICT": ConsistencyIssueType.ASSESSMENT,
        "COGNITIVE_LEVEL_MISMATCH": ConsistencyIssueType.PEDAGOGICAL,
        "SCAFFOLDING_DISCONTINUITY": ConsistencyIssueType.PEDAGOGICAL,
        "PREREQUISITE_ASSUMPTION_VIOLATION": ConsistencyIssueType.PEDAGOGICAL,
        "LEARNING_OBJECTIVE_CONTRADICTION": ConsistencyIssueType.PEDAGOGICAL,
        "COMPLEXITY_PROGRESSION_VIOLATION": ConsistencyIssueType.PEDAGOGICAL,
        "SKILL_TRANSFER_IMPEDIMENT": ConsistencyIssueType.PEDAGOGICAL,
    }

    category_key = (
        str(issue.category) if isinstance(issue.category, int) else issue.category
    )

    if category_key not in category_map:
        raise ValueError(f"Unknown category: {category_key}")

    return ConsistencyIssue(
        description=issue.description,
        severity=severity_map[issue.severity],
        type=category_to_type_map[category_key],
        category=category_map[category_key],
        primary_location=primary_location,
        related_locations=related_locations,
        suggested_fix=issue.suggested_fix,
    )


def convert_result_to_protobuf(result: ConsistencyResult) -> List[ConsistencyIssue]:
    """Convert Pydantic result model to list of protobuf ConsistencyIssue."""
    return [convert_consistency_issue_to_protobuf(issue) for issue in result.issues]
