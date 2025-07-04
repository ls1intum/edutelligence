"""Pydantic models for Step 3: Create Solution Repository."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseLanguageModel

from app.grpc import hyperion_pb2
from app.grpc.models import (
    GrpcMessage,
    BoundaryConditions,
    ProblemStatement,
    Repository,
)


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

    class Config:
        arbitrary_types_allowed = True


class SolutionRepositoryCreatorRequest(GrpcMessage):
    """Request for creating solution repository."""

    boundary_conditions: BoundaryConditions = Field(
        ..., description="Exercise boundary conditions"
    )
    problem_statement: ProblemStatement = Field(..., description="Problem statement")

    def to_grpc(self) -> hyperion_pb2.SolutionRepositoryCreatorRequest:
        return hyperion_pb2.SolutionRepositoryCreatorRequest(
            boundary_conditions=self.boundary_conditions.to_grpc(),
            problem_statement=self.problem_statement.to_grpc(),
        )

    @classmethod
    def from_grpc(
        cls, grpc_request: hyperion_pb2.SolutionRepositoryCreatorRequest
    ) -> "SolutionRepositoryCreatorRequest":
        return cls(
            boundary_conditions=BoundaryConditions.from_grpc(
                grpc_request.boundary_conditions
            ),
            problem_statement=ProblemStatement.from_grpc(
                grpc_request.problem_statement
            ),
        )


class SolutionRepositoryCreatorResponse(GrpcMessage):
    """Response from creating solution repository."""

    boundary_conditions: BoundaryConditions = Field(
        ..., description="Exercise boundary conditions"
    )
    problem_statement: ProblemStatement = Field(..., description="Problem statement")
    solution_repository: Repository = Field(
        ..., description="Generated solution repository"
    )
    success: bool = Field(..., description="Whether creation was successful")
    error_message: Optional[str] = Field(
        None, description="Error message if creation failed"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    def to_grpc(self) -> hyperion_pb2.SolutionRepositoryCreatorResponse:
        return hyperion_pb2.SolutionRepositoryCreatorResponse(
            boundary_conditions=self.boundary_conditions.to_grpc(),
            problem_statement=self.problem_statement.to_grpc(),
            solution_repository=self.solution_repository.to_grpc(),
        )

    @classmethod
    def from_grpc(
        cls, grpc_response: hyperion_pb2.SolutionRepositoryCreatorResponse
    ) -> "SolutionRepositoryCreatorResponse":
        return cls(
            boundary_conditions=BoundaryConditions.from_grpc(
                grpc_response.boundary_conditions
            ),
            problem_statement=ProblemStatement.from_grpc(
                grpc_response.problem_statement
            ),
            solution_repository=Repository.from_grpc(grpc_response.solution_repository),
            success=True,  # Default to success for now
            error_message=None,  # Default to no error
        )
