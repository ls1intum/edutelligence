import sys
import grpc
import logging
from typing import Optional
from concurrent import futures
from logging import StreamHandler, getLogger

from app.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[StreamHandler(sys.stdout)],
)

logger = getLogger(__name__)


class GrpcServer:
    """gRPC server for Nebula."""

    def __init__(self, host: str = "0.0.0.0", port: int = 50051, max_workers: int = 10):
        """Initialize the gRPC server.

        Args:
            host: Host to bind the server to
            port: Port to bind the server to
            max_workers: Maximum number of worker threads
        """
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self.server: Optional[grpc.Server] = None
        self._address = f"{host}:{port}"

    def start(self):
        """Start the gRPC server."""
        # Create a server with a thread pool
        self.server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=self.max_workers),
            options=[
                ("grpc.max_send_message_length", 100 * 1024 * 1024),  # 100 MB
                ("grpc.max_receive_message_length", 100 * 1024 * 1024),  # 100 MB
            ],
        )

        # Add services to the server
        # First add the health check service


        #faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQService(), server)

        # Register listening port
        self.server.add_insecure_port(self._address)

        # Start the server
        self.server.start()
        logger.info(f"gRPC server started, listening on {self._address}")

        # Keep the server running
        logger.info("Server waiting for requests...")
        self.server.wait_for_termination()


def serve():
    """Entry point for the grpc-server script."""
    logger.info("Starting Nebula gRPC server...")
    try:
        server = GrpcServer(
            host=settings.GRPC_HOST,
            port=settings.GRPC_PORT,
            max_workers=settings.GRPC_MAX_WORKERS,
        )
        logger.info(
            f"Server configured with host={settings.GRPC_HOST}, port={settings.GRPC_PORT}"
        )
        server.start()
    except Exception as e:
        logger.error(f"Failed to start gRPC server: {e}")
        raise
