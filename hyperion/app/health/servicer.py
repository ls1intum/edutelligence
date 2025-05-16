"""
Health check service implementation for Hyperion gRPC server.
"""

from logging import getLogger
import time
from app.grpc import hyperion_pb2, hyperion_pb2_grpc

logger = getLogger(__name__)

class HealthServicer(hyperion_pb2_grpc.HealthServicer):

    def __init__(self, version="0.1.0"):
        """Initialize the Health servicer.

        Args:
            version: The version of the server.
        """
        self.version = version
        logger.info(f"HealthServicer initialized with version {version}")

    def Ping(self, request, context):
        """Implement the Ping RPC method.

        Args:
            request: The PingRequest message
            context: The gRPC context

        Returns:
            PingResponse message
        """
        client_id = request.client_id if request.client_id else "unknown"
        logger.info(f"Received ping from client {client_id}")

        response = hyperion_pb2.PingResponse(
            status="OK", version=self.version, timestamp=int(time.time())
        )

        return response
