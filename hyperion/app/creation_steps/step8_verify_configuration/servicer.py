from app.grpc import hyperion_pb2_grpc
from app.grpc.utils import validate_grpc_request

from .models import (
    InconsistencyCheckRequest,
    InconsistencyCheckResponse,
)


class VerifyConfigurationServicer(hyperion_pb2_grpc.VerifyConfigurationServicer):

    @validate_grpc_request(InconsistencyCheckRequest)
    async def CheckInconsistencies(self, request: InconsistencyCheckRequest, context):
        response = InconsistencyCheckResponse(inconsistencies="test")
        return response.to_grpc()
