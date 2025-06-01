import sys
import grpc
import logging
from typing import Optional
from concurrent import futures
from logging import StreamHandler, getLogger
from langchain_core.language_models.chat_models import BaseLanguageModel

from app.settings import settings
from app.project_meta import project_meta
from app.grpc import hyperion_pb2_grpc
from app.models import get_model

from app.health.servicer import HealthServicer
from app.creation_steps.step1_define_boundary_condition.servicer import (
    DefineBoundaryConditionServicer,
)
from app.creation_steps.step2_draft_problem_statement.servicer import (
    DraftProblemStatementServicer,
)
from app.creation_steps.step3_create_solution_repository.servicer import (
    SolutionRepositoryCreatorServicer,
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
    """gRPC server for Hyperion."""

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
        self.model: Optional[BaseLanguageModel] = None

    def _initialize_model(self) -> BaseLanguageModel:
        """Initialize the AI model based on settings.
        
        Returns:
            Initialized language model instance
            
        Raises:
            ValueError: If model configuration is invalid
            EnvironmentError: If model provider is not found
        """
        if not settings.MODEL_NAME:
            raise ValueError("MODEL_NAME is not configured in settings")
        
        logger.info(f"Initializing AI model: {settings.MODEL_NAME}")
        try:
            model = get_model(settings.MODEL_NAME)
            logger.info(f"Successfully initialized model: {settings.MODEL_NAME}")
            return model
        except Exception as e:
            logger.error(f"Failed to initialize model {settings.MODEL_NAME}: {e}")
            raise

    def start(self):
        """Start the gRPC server."""
        self.model = self._initialize_model()
        
        self.server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=self.max_workers),
            options=[
                ("grpc.max_send_message_length", 100 * 1024 * 1024),  # 100 MB
                ("grpc.max_receive_message_length", 100 * 1024 * 1024),  # 100 MB
            ],
        )

        # Add services to the server
        hyperion_pb2_grpc.add_HealthServicer_to_server(
            HealthServicer(version=project_meta.version), self.server
        )
        hyperion_pb2_grpc.add_DefineBoundaryConditionServicer_to_server(
            DefineBoundaryConditionServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_DraftProblemStatementServicer_to_server(
            DraftProblemStatementServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_SolutionRepositoryCreatorServicer_to_server(
            SolutionRepositoryCreatorServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_CreateTemplateRepositoryServicer_to_server(
            CreateTemplateRepositoryServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_CreateTestRepositoryServicer_to_server(
            CreateTestRepositoryServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_FinalizeProblemStatementServicer_to_server(
            FinalizeProblemStatementServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_ConfigureGradingServicer_to_server(
            ConfigureGradingServicer(model=self.model), self.server
        )
        hyperion_pb2_grpc.add_VerifyConfigurationServicer_to_server(
            VerifyConfigurationServicer(model=self.model), self.server
        )

        # Register listening port
        self.server.add_insecure_port(self._address)

        # Start the server
        self.server.start()
        logger.info(f"gRPC server started, listening on {self._address}")
        logger.info(f"Using LM model: {settings.MODEL_NAME}")

        # Keep the server running
        logger.info("Server waiting for requests...")
        self.server.wait_for_termination()


def serve():
    """Entry point for the grpc-server script."""
    logger.info("Starting Hyperion gRPC server...")
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
