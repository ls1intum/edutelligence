"""Pydantic models for Step 3: Create Solution Repository."""

from typing import List, Optional, Dict, Any, TYPE_CHECKING
from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseLanguageModel

if TYPE_CHECKING:
    from app.grpc import hyperion_pb2


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

    # Use string annotations to avoid import-time dependency on gRPC
    boundary_conditions: "hyperion_pb2.SolutionRepositoryCreatorRequest" = Field(
        ..., description="Exercise boundary conditions from gRPC request"
    )
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
    solution_repository: Optional["hyperion_pb2.Repository"] = Field(
        None, description="Generated solution repository"
    )
    fix_attempts: List[FixAttempt] = Field(
        default_factory=list, description="Fix attempts made"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    class Config:
        arbitrary_types_allowed = True
