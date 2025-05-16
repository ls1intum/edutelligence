from app.grpc import hyperion_pb2_grpc

from .models import (
    InconsistencyCheckRequest,
    InconsistencyCheckResponse,
)


class VerifyConfigurationServicer(hyperion_pb2_grpc.VerifyConfigurationServicer):

    async def CheckInconsistencies(self, request: InconsistencyCheckRequest, context):
        request = InconsistencyCheckRequest.from_grpc(request)
        response = InconsistencyCheckResponse(inconsistencies="test")
        return response.to_grpc()
