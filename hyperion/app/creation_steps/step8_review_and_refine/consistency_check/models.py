from enum import Enum
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

from app.creation_steps.models import Metadata, Repository


class ProgrammingLanguage(str, Enum):
    """Programming language enumeration for consistency checking."""

    JAVA = "java"
    PYTHON = "python"
    # Future extensions can add more languages


class LanguageConfig(BaseModel):
    """Configuration for language-specific context rendering."""

    file_extensions: List[str] = Field(
        description="File extensions to include in context rendering"
    )
    source_directories: List[str] = Field(
        description="Source directories to search for files"
    )
    exclude_patterns: List[str] = Field(
        default_factory=list, description="File patterns to exclude from context"
    )
    max_file_size_kb: int = Field(
        default=100, description="Maximum file size in KB to include in context"
    )


# Language-specific configurations
LANGUAGE_CONFIGS: Dict[ProgrammingLanguage, LanguageConfig] = {
    ProgrammingLanguage.JAVA: LanguageConfig(
        file_extensions=[".java"],
        source_directories=["src"],
        exclude_patterns=[
            "*/target/*", 
            "*/build/*", 
            "*/.gradle/*",
            "gradle/*",
            "gradlew*",
            "*.gradle", 
            "*.properties",
            "*.bat",
            "*.sh",
            ".gradle/*"
        ],
        max_file_size_kb=50,
    ),
    ProgrammingLanguage.PYTHON: LanguageConfig(
        file_extensions=[".py"],
        source_directories=["src", ".", "lib"],
        exclude_patterns=["**/__pycache__/**", "**/*.pyc", "**/venv/**", "**/env/**"],
        max_file_size_kb=50,
    ),
}


class ArtifactType(str, Enum):
    """Artifact type enumeration."""

    PROBLEM_STATEMENT = "PROBLEM_STATEMENT"
    TEMPLATE_REPOSITORY = "TEMPLATE_REPOSITORY"
    SOLUTION_REPOSITORY = "SOLUTION_REPOSITORY"

    # Ignored for now
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
    template_repository: Repository = Field(
        ..., description="Template repository to check"
    )
    programming_language: ProgrammingLanguage = Field(
        ..., description="Programming language for language-specific context rendering"
    )
    # Optional repositories - can be added in future
    solution_repository: Optional[Repository] = Field(
        None, description="Solution repository to check (optional)"
    )
    test_repository: Optional[Repository] = Field(
        None, description="Test repository to check (optional)"
    )


class ContextRenderingConfig(BaseModel):
    """Configuration for context rendering based on programming language."""

    programming_language: ProgrammingLanguage = Field(
        description="Programming language for context rendering"
    )
    language_config: LanguageConfig = Field(
        description="Language-specific configuration"
    )
    include_file_structure: bool = Field(
        default=True,
        description="Whether to include file structure overview in context",
    )
    max_context_size_kb: int = Field(
        default=500, description="Maximum total context size in KB"
    )

    @classmethod
    def for_language(cls, language: ProgrammingLanguage) -> "ContextRenderingConfig":
        """Create configuration for specific programming language."""
        if language not in LANGUAGE_CONFIGS:
            raise ValueError(f"Unsupported programming language: {language}")

        return cls(
            programming_language=language, language_config=LANGUAGE_CONFIGS[language]
        )


class ConsistencyCheckResponse(BaseModel):
    """Response model for consistency check"""

    issues: List[ConsistencyIssue] = Field(
        ..., description="List of consistency issues found"
    )
    metadata: Metadata = Field(..., description="Response metadata")
