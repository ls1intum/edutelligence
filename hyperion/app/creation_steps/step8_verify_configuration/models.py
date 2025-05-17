from pydantic import Field

from app.grpc import hyperion_pb2
from app.grpc.models import GrpcMessage, Repository


class InconsistencyCheckRequest(GrpcMessage):
    problem_statement: str = Field(..., description="The problem statement text")
    solution_repository: Repository = Field(
        ..., description="Repository containing solution files"
    )
    template_repository: Repository = Field(
        ..., description="Repository containing template files"
    )
    test_repository: Repository = Field(
        ..., description="Repository containing test files"
    )

    def to_grpc(self) -> hyperion_pb2.InconsistencyCheckRequest:
        return hyperion_pb2.InconsistencyCheckRequest(
            problem_statement=self.problem_statement,
            solution_repository=self.solution_repository.to_grpc(),
            template_repository=self.template_repository.to_grpc(),
            test_repository=self.test_repository.to_grpc(),
        )

    @classmethod
    def from_grpc(
        cls, grpc_request: hyperion_pb2.InconsistencyCheckRequest
    ) -> "InconsistencyCheckRequest":
        return cls(
            problem_statement=grpc_request.problem_statement,
            solution_repository=Repository.from_grpc(grpc_request.solution_repository),
            template_repository=Repository.from_grpc(grpc_request.template_repository),
            test_repository=Repository.from_grpc(grpc_request.test_repository),
        )


class InconsistencyCheckResponse(GrpcMessage):
    inconsistencies: str = Field(
        ..., description="A string describing the inconsistencies found"
    )

    def to_grpc(self) -> hyperion_pb2.InconsistencyCheckResponse:
        return hyperion_pb2.InconsistencyCheckResponse(
            inconsistencies=self.inconsistencies
        )

    @classmethod
    def from_grpc(
        cls, grpc_response: hyperion_pb2.InconsistencyCheckResponse
    ) -> "InconsistencyCheckResponse":
        return cls(inconsistencies=grpc_response.inconsistencies)
