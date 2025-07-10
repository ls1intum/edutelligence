"""Pydantic models for gRPC message conversion."""

from typing import List, Optional
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod

from . import hyperion_pb2


class GrpcMessage(BaseModel, ABC):
    """Base class for gRPC message conversion."""

    @abstractmethod
    def to_grpc(self):
        """Convert to gRPC message."""
        pass

    @classmethod
    @abstractmethod
    def from_grpc(cls, grpc_message):
        """Convert from gRPC message."""
        pass


class RepositoryFile(GrpcMessage):
    """Represents a file in a repository."""

    path: str = Field(..., description="File path relative to repository root")
    content: str = Field(..., description="File content")

    def to_grpc(self) -> hyperion_pb2.RepositoryFile:
        return hyperion_pb2.RepositoryFile(path=self.path, content=self.content)

    @classmethod
    def from_grpc(cls, grpc_file: hyperion_pb2.RepositoryFile) -> "RepositoryFile":
        return cls(path=grpc_file.path, content=grpc_file.content)


class Repository(GrpcMessage):
    """Represents a collection of files that form a repository."""

    files: List[RepositoryFile] = Field(
        default_factory=list, description="Files in the repository"
    )

    def to_grpc(self) -> hyperion_pb2.Repository:
        return hyperion_pb2.Repository(files=[file.to_grpc() for file in self.files])

    @classmethod
    def from_grpc(cls, grpc_repo: hyperion_pb2.Repository) -> "Repository":
        return cls(files=[RepositoryFile.from_grpc(file) for file in grpc_repo.files])


class BoundaryConditions(GrpcMessage):
    """Represents boundary conditions for a programming exercise."""

    programming_language: int = Field(
        ..., description="Programming language enum value"
    )
    project_type: int = Field(..., description="Project type enum value")
    difficulty: str = Field(..., description="Difficulty level")
    points: int = Field(..., description="Points for the exercise")
    bonus_points: int = Field(default=0, description="Bonus points")
    constraints: List[str] = Field(
        default_factory=list, description="Additional constraints"
    )

    def to_grpc(self) -> hyperion_pb2.SolutionRepositoryCreatorRequest:
        # Since we flattened the structure, we need to create a partial request
        # This method should not be called directly
        raise NotImplementedError(
            "BoundaryConditions should be part of a request/response"
        )

    @classmethod
    def from_grpc(cls, grpc_message) -> "BoundaryConditions":
        # Handle both request and response messages
        return cls(
            programming_language=grpc_message.programming_language,
            project_type=grpc_message.project_type,
            difficulty=grpc_message.difficulty,
            points=grpc_message.points,
            bonus_points=grpc_message.bonus_points,
            constraints=list(grpc_message.constraints),
        )


class ProblemStatement(GrpcMessage):
    """Represents a problem statement for a programming exercise."""

    title: str = Field(..., description="Exercise title")
    short_title: str = Field(..., description="Short title")
    description: str = Field(..., description="Problem description")

    def to_grpc(self) -> hyperion_pb2.SolutionRepositoryCreatorRequest:
        # Since we flattened the structure, we need to create a partial request
        # This method should not be called directly
        raise NotImplementedError(
            "ProblemStatement should be part of a request/response"
        )

    @classmethod
    def from_grpc(cls, grpc_message) -> "ProblemStatement":
        # Handle both request and response messages
        return cls(
            title=grpc_message.title,
            short_title=grpc_message.short_title,
            description=grpc_message.description,
        )
