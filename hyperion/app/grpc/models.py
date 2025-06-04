"""Pydantic models for gRPC messages."""

from typing import List
from pydantic import BaseModel, Field
from enum import Enum

from app.grpc import hyperion_pb2


class GrpcMessage(BaseModel):
    """Abstract base class for gRPC messages."""

    def to_grpc(self):
        """Convert to gRPC message."""
        raise NotImplementedError("Subclasses must implement this method")

    @classmethod
    def from_grpc(cls, grpc_message):
        """Create from gRPC message."""
        raise NotImplementedError("Subclasses must implement this method")


class ProgrammingLanguage(str, Enum):
    """Enum for programming languages."""

    EMPTY = "EMPTY"
    ASSEMBLER = "ASSEMBLER"
    BASH = "BASH"
    C = "C"
    C_PLUS_PLUS = "C_PLUS_PLUS"
    C_SHARP = "C_SHARP"
    DART = "DART"
    GO = "GO"
    HASKELL = "HASKELL"
    JAVA = "JAVA"
    JAVASCRIPT = "JAVASCRIPT"
    KOTLIN = "KOTLIN"
    MATLAB = "MATLAB"
    OCAML = "OCAML"
    PYTHON = "PYTHON"
    R = "R"
    RUBY = "RUBY"
    RUST = "RUST"
    SWIFT = "SWIFT"
    TYPESCRIPT = "TYPESCRIPT"
    VHDL = "VHDL"


class ProjectType(str, Enum):
    """Enum for project types."""

    MAVEN_MAVEN = "MAVEN_MAVEN"
    PLAIN_MAVEN = "PLAIN_MAVEN"
    MAVEN_BLACKBOX = "MAVEN_BLACKBOX"
    PLAIN_GRADLE = "PLAIN_GRADLE"
    GRADLE_GRADLE = "GRADLE_GRADLE"
    PLAIN = "PLAIN"
    XCODE = "XCODE"
    FACT = "FACT"
    GCC = "GCC"


class RepositoryFile(GrpcMessage):
    path: str = Field(..., description="File path relative to the repository root")
    content: str = Field(..., description="File content")

    def to_grpc(self) -> hyperion_pb2.RepositoryFile:
        return hyperion_pb2.RepositoryFile(path=self.path, content=self.content)

    @classmethod
    def from_grpc(cls, grpc_file: hyperion_pb2.RepositoryFile) -> "RepositoryFile":
        return cls(path=grpc_file.path, content=grpc_file.content)


class Repository(GrpcMessage):
    files: List[RepositoryFile] = Field(
        ..., description="Files contained in the repository"
    )

    def to_grpc(self) -> hyperion_pb2.Repository:
        return hyperion_pb2.Repository(files=[file.to_grpc() for file in self.files])

    @classmethod
    def from_grpc(cls, grpc_repo: hyperion_pb2.Repository) -> "Repository":
        return cls(files=[RepositoryFile.from_grpc(file) for file in grpc_repo.files])


class ProgrammingExercise(BaseModel):
    id: int = Field(..., description="Unique identifier for the exercise")
    title: str = Field(..., description="Title of the exercise")
    programming_language: ProgrammingLanguage = Field(
        ..., description="Programming language used"
    )
    package_name: str = Field(..., description="Package name for the exercise")
    project_type: ProjectType = Field(
        ..., description="Type of project (e.g., Maven, Gradle)"
    )
    template_repository: Repository = Field(
        ..., description="Repository containing template files"
    )
    solution_repository: Repository = Field(
        ..., description="Repository containing solution files"
    )
    test_repository: Repository = Field(
        ..., description="Repository containing test files"
    )
    problem_statement: str = Field(
        ..., description="Problem statement describing the exercise requirements"
    )

    def to_grpc(self) -> hyperion_pb2.ProgrammingExercise:
        return hyperion_pb2.ProgrammingExercise(
            id=self.id,
            title=self.title,
            programming_language=getattr(
                hyperion_pb2.ProgrammingLanguage, self.programming_language
            ),
            package_name=self.package_name,
            project_type=getattr(hyperion_pb2.ProjectType, self.project_type),
            template_repository=self.template_repository.to_grpc(),
            solution_repository=self.solution_repository.to_grpc(),
            test_repository=self.test_repository.to_grpc(),
            problem_statement=self.problem_statement,
        )

    @classmethod
    def from_grpc(
        cls, grpc_exercise: hyperion_pb2.ProgrammingExercise
    ) -> "ProgrammingExercise":
        return cls(
            id=grpc_exercise.id,
            title=grpc_exercise.title,
            programming_language=hyperion_pb2.ProgrammingLanguage.Name(
                grpc_exercise.programming_language
            ),
            package_name=grpc_exercise.package_name,
            project_type=hyperion_pb2.ProjectType.Name(grpc_exercise.project_type),
            template_repository=Repository.from_grpc(grpc_exercise.template_repository),
            solution_repository=Repository.from_grpc(grpc_exercise.solution_repository),
            test_repository=Repository.from_grpc(grpc_exercise.test_repository),
            problem_statement=grpc_exercise.problem_statement,
        )


class BoundaryConditions(GrpcMessage):
    """Boundary conditions for programming exercises."""
    programming_language: ProgrammingLanguage = Field(..., description="Programming language")
    project_type: ProjectType = Field(..., description="Project type")
    difficulty: str = Field(..., description="Exercise difficulty")
    points: int = Field(..., description="Points for the exercise")

    def to_grpc(self) -> hyperion_pb2.BoundaryConditions:
        return hyperion_pb2.BoundaryConditions(
            programming_language=getattr(hyperion_pb2.ProgrammingLanguage, self.programming_language),
            project_type=getattr(hyperion_pb2.ProjectType, self.project_type),
            difficulty=self.difficulty,
            points=self.points
        )

    @classmethod
    def from_grpc(cls, grpc_bc: hyperion_pb2.BoundaryConditions) -> "BoundaryConditions":
        return cls(
            programming_language=hyperion_pb2.ProgrammingLanguage.Name(grpc_bc.programming_language),
            project_type=hyperion_pb2.ProjectType.Name(grpc_bc.project_type),
            difficulty=grpc_bc.difficulty,
            points=grpc_bc.points
        )


class ProblemStatement(GrpcMessage):
    """Problem statement for programming exercises."""
    title: str = Field(..., description="Exercise title")
    description: str = Field(..., description="Exercise description")

    def to_grpc(self) -> hyperion_pb2.ProblemStatement:
        return hyperion_pb2.ProblemStatement(
            title=self.title,
            description=self.description
        )

    @classmethod
    def from_grpc(cls, grpc_ps: hyperion_pb2.ProblemStatement) -> "ProblemStatement":
        return cls(
            title=grpc_ps.title,
            description=grpc_ps.description
        )
