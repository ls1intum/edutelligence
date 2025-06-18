import logging
from typing import Dict, Any, Optional, List
from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc, hyperion_pb2
from app.grpc.models import Repository

from .models import (
    SolutionRepositoryCreatorRequest,
    SolutionRepositoryCreatorResponse,
    SolutionCreationContext,
)
from .code_generator import CodeGenerator
from ..workspace import TempWorkspaceManager
from .language_handlers import registry as language_registry
from .exceptions import SolutionCreatorException, LanguageHandlerException
from ..config import config

import grpc

logger = logging.getLogger(__name__)


class SolutionRepositoryCreatorServicer(
    hyperion_pb2_grpc.SolutionRepositoryCreatorServicer
):
    """
    Step 3: Create Solution Repository

    This service receives:
    - BoundaryConditions (from step 1)
    - ProblemStatement (from step 2)

    And creates:
    - Solution Repository (the actual solution code)

    Returns all previous data plus the new solution repository.
    """

    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for solution generation
        """
        self.model = model
        self.workspace_manager = TempWorkspaceManager()
        self.code_generator = CodeGenerator(model=model)

    async def CreateSolutionRepository(
        self, request: hyperion_pb2.SolutionRepositoryCreatorRequest, context: Any
    ) -> hyperion_pb2.SolutionRepositoryCreatorResponse:
        """
        Create a solution repository based on boundary conditions and problem statement.

        Args:
            request: Contains boundary conditions and problem statement
            context: gRPC context

        Returns:
            SolutionRepositoryCreatorResponse: Contains all input data plus the created solution repository
        """
        logger.info("Creating solution repository...")

        try:
            request_model = SolutionRepositoryCreatorRequest.from_grpc(request)

            solution_context: SolutionCreationContext = self._initialize_context(
                request_model
            )
            self._validate_language_support(solution_context)

            workspace_path: str = self.workspace_manager.create_workspace(
                solution_context
            )
            solution_context.workspace_path = workspace_path

            solution_context = await self.code_generator.execute(solution_context)

            response: SolutionRepositoryCreatorResponse = self._create_response(
                solution_context, request_model
            )

            self._cleanup_workspace(solution_context)

            logger.info("Solution repository created successfully")
            return response.to_grpc()

        except SolutionCreatorException as e:
            logger.error(f"Solution creator error: {str(e)}")
            context.abort(grpc.StatusCode.INTERNAL, f"Solution creation failed: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error creating solution repository: {str(e)}")
            context.abort(
                grpc.StatusCode.INTERNAL,
                f"Failed to create solution repository: {str(e)}",
            )

    def _initialize_context(
        self, request: SolutionRepositoryCreatorRequest
    ) -> SolutionCreationContext:
        return SolutionCreationContext(
            boundary_conditions=request.boundary_conditions,
            problem_statement=request.problem_statement,
            workspace_path="",  # Will be set after workspace creation
            model=self.model,
        )

    def _validate_language_support(self, context: SolutionCreationContext) -> None:
        language = context.boundary_conditions.programming_language
        if not language_registry.is_supported(language):
            supported_languages = language_registry.get_supported_languages()
            raise LanguageHandlerException(
                f"Programming language '{language}' is not supported",
                language=language,
                details={"supported_languages": supported_languages},
            )

    def _create_response(
        self,
        context: SolutionCreationContext,
        request: SolutionRepositoryCreatorRequest,
    ) -> SolutionRepositoryCreatorResponse:
        # Determine success based on context
        success = (
            context.solution_repository is not None
            and len(context.fix_attempts) < config.solution_creator_max_iterations
        )

        # Create error message if failed
        error_message = None
        if not success:
            if context.solution_repository is None:
                error_message = "Failed to generate solution repository"
            elif len(context.fix_attempts) >= config.solution_creator_max_iterations:
                error_message = f"Maximum iterations ({config.solution_creator_max_iterations}) exceeded"

        return SolutionRepositoryCreatorResponse(
            boundary_conditions=request.boundary_conditions,
            problem_statement=request.problem_statement,
            solution_repository=context.solution_repository
            or self._create_empty_repository(),
            success=success,
            error_message=error_message,
            metadata={
                "fix_attempts": len(context.fix_attempts),
                "workspace_path": context.workspace_path,
            },
        )

    def _create_empty_repository(self) -> Repository:
        return Repository(files=[])

    def _cleanup_workspace(self, context: SolutionCreationContext) -> None:
        try:
            # Determine if we should cleanup based on success and configuration
            should_cleanup = (
                context.solution_repository is not None and config.cleanup_on_success
            ) or (context.solution_repository is None and config.cleanup_on_failure)

            if should_cleanup:
                self.workspace_manager.cleanup_workspace(context)
                logger.info("Workspace cleaned up successfully")
            else:
                logger.info(f"Workspace preserved at: {context.workspace_path}")

        except Exception as e:
            logger.warning(f"Failed to cleanup workspace: {str(e)}")

    def get_supported_languages(self) -> List[str]:
        return language_registry.get_supported_languages()

    def get_language_info(self, language: str) -> Dict[str, Any]:
        return language_registry.get_handler_info(language) or {}
