import sys
import grpc
import logging
import signal
from typing import Optional
from concurrent import futures
from logging import StreamHandler, getLogger

from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from app.settings import settings
from app.project_meta import project_meta
from app.grpc import hyperion_pb2_grpc


from app.creation_steps.step1_define_boundary_condition.servicer import (
    DefineBoundaryConditionServicer,
)
from app.creation_steps.step2_draft_problem_statement.servicer import (
    DraftProblemStatementServicer,
)
from app.creation_steps.step3_create_solution_repository.servicer import (
    CreateSolutionRepositoryServicer,
)
from app.creation_steps.step4_create_template_repository.servicer import (
    CreateTemplateRepositoryServicer,
)
from app.creation_steps.step5_create_test_repository.servicer import (
    CreateTestRepositoryServicer,
)
from app.creation_steps.step6_finalize_problem_statement.servicer import (
    FinalizeProblemStatementServicer,
)
from app.creation_steps.step7_configure_grading.servicer import ConfigureGradingServicer
from app.creation_steps.step8_verify_configuration.servicer import (
    VerifyConfigurationServicer,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[StreamHandler(sys.stdout)],
)

logger = getLogger(__name__)


class GrpcServer:
    """Production-grade gRPC server for Hyperion."""

    def __init__(self, max_workers: int = None):
        """Initialize the gRPC server.

        Args:
            max_workers: Maximum number of worker threads (defaults to settings)
        """
        self.max_workers = max_workers or settings.GRPC_MAX_WORKERS
        self.server: Optional[grpc.Server] = None
        self._shutdown_event = False

    def start(self):
        """Start the gRPC server."""
        # Create server with interceptors for observability
        self.server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=self.max_workers),
            options=[
                ("grpc.max_send_message_length", 100 * 1024 * 1024),  # 100 MB
                ("grpc.max_receive_message_length", 100 * 1024 * 1024),  # 100 MB
                ("grpc.keepalive_time_ms", 30000),  # 30 seconds
                ("grpc.keepalive_timeout_ms", 5000),  # 5 seconds
                ("grpc.keepalive_permit_without_calls", True),
                ("grpc.http2.min_time_between_pings_ms", 10000),  # 10 seconds
                ("grpc.http2.min_ping_interval_without_data_ms", 300000),  # 5 minutes
            ],
        )

        # Register services dynamically
        self._register_services()

        # Configure TLS or insecure port
        if settings.TLS_ENABLED:
            self._configure_tls_port()
        else:
            # Development mode - insecure port
            self.server.add_insecure_port(settings.GRPC_ADDRESS)
            logger.warning("Using insecure gRPC port - NOT recommended for production!")

        # Setup graceful shutdown
        self._setup_signal_handlers()

        # Start the server
        self.server.start()
        logger.info(
            f"gRPC server started, listening on {settings.GRPC_ADDRESS} (TLS: {settings.TLS_ENABLED})"
        )

        # Keep the server running
        logger.info("Server waiting for requests...")
        try:
            self.server.wait_for_termination()
        except KeyboardInterrupt:
            self._graceful_shutdown()

    def _register_services(self):
        """Register all gRPC services dynamically."""
        logger.info("Registering gRPC services...")

        # Add health service using the official gRPC health protocol
        health_servicer = health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, self.server)

        # Set overall server health status to SERVING
        health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)

        # Map of servicer classes to their registration functions
        servicers = {
            "DefineBoundaryConditionServicer": DefineBoundaryConditionServicer(),
            "DraftProblemStatementServicer": DraftProblemStatementServicer(),
            "CreateSolutionRepositoryServicer": CreateSolutionRepositoryServicer(),
            "CreateTemplateRepositoryServicer": CreateTemplateRepositoryServicer(),
            "CreateTestRepositoryServicer": CreateTestRepositoryServicer(),
            "FinalizeProblemStatementServicer": FinalizeProblemStatementServicer(),
            "ConfigureGradingServicer": ConfigureGradingServicer(),
            "VerifyConfigurationServicer": VerifyConfigurationServicer(),
        }

        # Register each servicer and set their health status
        for servicer_name, servicer_instance in servicers.items():
            add_fn_name = f"add_{servicer_name}_to_server"
            add_fn = getattr(hyperion_pb2_grpc, add_fn_name, None)
            if add_fn:
                add_fn(servicer_instance, self.server)
                logger.info(f"Registered {servicer_name}")

                # Set health status for this service
                service_name = servicer_name.replace("Servicer", "")
                health_servicer.set(
                    service_name, health_pb2.HealthCheckResponse.SERVING
                )
            else:
                logger.warning(f"Could not find registration function: {add_fn_name}")

        # Store health servicer reference for shutdown handling
        self._health_servicer = health_servicer

    def _setup_signal_handlers(self):
        """Setup graceful shutdown signal handlers."""

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self._graceful_shutdown()

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def _graceful_shutdown(self):
        """Perform graceful shutdown of the gRPC server."""
        if self.server and not self._shutdown_event:
            self._shutdown_event = True
            logger.info("Initiating graceful shutdown...")

            # Set all services to NOT_SERVING during shutdown
            if hasattr(self, "_health_servicer"):
                self._health_servicer.set(
                    "", health_pb2.HealthCheckResponse.NOT_SERVING
                )
                logger.info("Set server health status to NOT_SERVING")

            # Stop accepting new requests and give existing ones time to complete
            self.server.stop(grace=30)  # 30 second grace period
            logger.info("Graceful shutdown complete")

    def _configure_tls_port(self):
        """Configure TLS for production gRPC server."""
        try:
            # Read certificate files
            with open(settings.TLS_CERT_PATH, "rb") as f:
                certificate_chain = f.read()
            with open(settings.TLS_KEY_PATH, "rb") as f:
                private_key = f.read()

            # Optional: Client certificate verification
            root_certificates = None
            if settings.TLS_CA_PATH:
                with open(settings.TLS_CA_PATH, "rb") as f:
                    root_certificates = f.read()
                logger.info("Client certificate verification enabled")

            # Create server credentials
            server_credentials = grpc.ssl_server_credentials(
                [(private_key, certificate_chain)],
                root_certificates=root_certificates,
                require_client_auth=bool(root_certificates),
            )

            # Add secure port
            self.server.add_secure_port(settings.GRPC_ADDRESS, server_credentials)
            logger.info(f"TLS enabled with certificate: {settings.TLS_CERT_PATH}")

        except Exception as e:
            logger.error(f"Failed to configure TLS: {e}")
            raise RuntimeError(f"TLS configuration failed: {e}")


def serve():
    """Entry point for the grpc-server script."""
    logger.info("Starting Hyperion gRPC server...")
    try:
        server = GrpcServer(max_workers=settings.GRPC_MAX_WORKERS)
        logger.info(
            f"Server configured with address={settings.GRPC_ADDRESS}, workers={settings.GRPC_MAX_WORKERS}"
        )
        server.start()
    except Exception as e:
        logger.error(f"Failed to start gRPC server: {e}")
        raise


if __name__ == "__main__":
    serve()
