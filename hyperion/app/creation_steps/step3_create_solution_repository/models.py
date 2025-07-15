"""Pydantic models for Step 3: Create Solution Repository."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseLanguageModel
from enum import Enum

from app.creation_steps.models import Repository, Metadata


class ProgrammingLanguage(str, Enum):
    """Programming language enumeration matching Artemis."""

    EMPTY = ""
    JAVA = "java"
    PYTHON = "python"
    C = "c"
    HASKELL = "haskell"
    KOTLIN = "kotlin"
    VHDL = "vhdl"
    ASSEMBLER = "assembler"
    SWIFT = "swift"
    OCAML = "ocaml"
    JAVASCRIPT = "javascript"
    C_SHARP = "csharp"
    C_PLUS_PLUS = "cpp"
    SQL = "sql"
    R = "r"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    GO = "go"
    MATLAB = "matlab"
    BASH = "bash"
    RUBY = "ruby"
    POWERSHELL = "powershell"
    ADA = "ada"
    DART = "dart"
    PHP = "php"


class ProjectType(str, Enum):
    """Project type enumeration matching Artemis."""

    MAVEN_MAVEN = "maven_maven"
    PLAIN_MAVEN = "plain_maven"
    PLAIN = "plain"
    XCODE = "xcode"
    FACT = "fact"
    GCC = "gcc"
    PLAIN_GRADLE = "plain_gradle"
    GRADLE_GRADLE = "gradle_gradle"
    MAVEN_BLACKBOX = "maven_blackbox"


class BoundaryConditions(BaseModel):
    """Exercise boundary conditions."""

    programming_language: ProgrammingLanguage = Field(
        ..., description="Programming language for the exercise"
    )
    project_type: ProjectType = Field(..., description="Project type and build system")
    difficulty: str = Field(..., description="Difficulty level")
    points: int = Field(..., description="Points awarded for completion")
    bonus_points: int = Field(default=0, description="Bonus points available")
    constraints: List[str] = Field(
        default_factory=list, description="Additional constraints"
    )


class ProblemStatement(BaseModel):
    """Problem statement definition."""

    title: str = Field(..., description="Exercise title")
    short_title: str = Field(..., description="Abbreviated title")
    description: str = Field(..., description="Detailed problem description")


class SolutionRepositoryCreatorRequest(BaseModel):
    """Request for creating solution repository."""

    boundary_conditions: BoundaryConditions = Field(
        ..., description="Exercise boundary conditions"
    )
    problem_statement: ProblemStatement = Field(..., description="Problem statement")


class SolutionRepositoryCreatorResponse(BaseModel):
    """Response for solution repository creation."""

    repository: Repository = Field(..., description="Generated solution repository")
    metadata: Metadata = Field(..., description="Response metadata")


class SolutionPlan(BaseModel):
    """High-level solution architecture plan."""

    architecture_description: str = Field(
        ..., description="High-level solution architecture"
    )
    required_classes: List[str] = Field(
        default_factory=list, description="Required classes"
    )
    required_functions: List[str] = Field(
        default_factory=list, description="Required functions"
    )
    algorithms: List[str] = Field(
        default_factory=list, description="Algorithms to be used"
    )
    design_patterns: List[str] = Field(
        default_factory=list, description="Design patterns to apply"
    )


class FileStructure(BaseModel):
    """Project file structure definition."""

    directories: List[str] = Field(
        default_factory=list, description="Directories to create"
    )
    files: List[str] = Field(default_factory=list, description="Files to create")
    build_files: List[str] = Field(
        default_factory=list, description="Build configuration files"
    )


class FixAttempt(BaseModel):
    """Single fix attempt during iterative fixing."""

    iteration: int = Field(..., description="Iteration number")
    issue_description: str = Field(
        ..., description="Description of the issue being fixed"
    )
    fix_description: str = Field(..., description="Description of the fix applied")
    files_modified: List[str] = Field(
        default_factory=list, description="Files that were modified"
    )
    success: bool = Field(..., description="Whether the fix was successful")


class SolutionCreationContext(BaseModel):
    """Context object passed between phases and steps."""

    boundary_conditions: BoundaryConditions = Field(
        ..., description="Exercise boundary conditions"
    )
    problem_statement: ProblemStatement = Field(..., description="Problem statement")
    workspace_path: str = Field(..., description="Path to temporary workspace")
    model: Optional[BaseLanguageModel] = Field(
        None, description="AI language model for generation", exclude=True
    )
    solution_plan: Optional[SolutionPlan] = Field(
        None, description="Generated solution plan"
    )
    file_structure: Optional[FileStructure] = Field(
        None, description="Defined file structure"
    )
    solution_repository: Optional[Repository] = Field(
        None, description="Generated solution repository"
    )
    fix_attempts: List[FixAttempt] = Field(
        default_factory=list, description="Fix attempts made"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    model_config = {"arbitrary_types_allowed": True}
