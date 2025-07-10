import logging
from typing import Dict, Any, List, TYPE_CHECKING
from langchain_core.language_models.chat_models import BaseLanguageModel

from .models import (
    SolutionCreationContext,
)
from .code_generator import CodeGenerator
from .language_handlers import registry as language_registry
from .exceptions import SolutionCreatorException, LanguageHandlerException
from ..config import config
from ..workspace.workspace_manager import WorkspaceManager

import grpc

if TYPE_CHECKING:
    from app.grpc import hyperion_pb2_grpc, hyperion_pb2

logger = logging.getLogger(__name__)


class CreateSolutionRepositoryServicer:
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
        self.code_generator = CodeGenerator(model=model)
        self.workspace_manager = WorkspaceManager()

    async def CreateSolutionRepository(self, request, context: Any):
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
            # Import at runtime to avoid protobuf version issues
            from app.grpc import hyperion_pb2

            solution_context: SolutionCreationContext = self._initialize_context(
                request
            )
            self._validate_language_support(solution_context)

            # Create workspace using the workspace manager
            solution_context.workspace_path = self.workspace_manager.create_workspace(
                prefix="solution_creation_"
            )

            solution_context = await self.code_generator.execute(solution_context)

            response = self._create_response(solution_context, request)

            self._cleanup_workspace(solution_context)

            logger.info("Solution repository created successfully")
            return response

        except SolutionCreatorException as e:
            logger.error(f"Solution creator error: {str(e)}")
            context.abort(
                grpc.StatusCode.INTERNAL, f"Solution creation failed: {str(e)}"
            )

        except Exception as e:
            logger.error(f"Unexpected error creating solution repository: {str(e)}")
            context.abort(
                grpc.StatusCode.INTERNAL,
                f"Failed to create solution repository: {str(e)}",
            )

    def _initialize_context(self, request) -> SolutionCreationContext:
        return SolutionCreationContext(
            boundary_conditions=request,
            workspace_path="",  # Will be set after workspace creation
            model=self.model,
        )

    def _validate_language_support(self, context: SolutionCreationContext) -> None:
        language_enum = context.boundary_conditions.programming_language
        language_str = self._convert_language_enum_to_string(language_enum)
        if not language_registry.is_supported(language_str):
            supported_languages = language_registry.get_supported_languages()
            raise LanguageHandlerException(
                f"Programming language '{language_str}' is not supported",
                language=language_str,
                details={"supported_languages": supported_languages},
            )

    def _convert_language_enum_to_string(self, language_enum: int) -> str:
        """Convert programming language enum value to string using protobuf enum descriptor."""
        try:
            # Import at runtime to avoid protobuf version issues
            from app.grpc import hyperion_pb2
            
            # Use the protobuf enum descriptor to get the name
            enum_descriptor = hyperion_pb2.ProgrammingLanguage.DESCRIPTOR
            enum_value = enum_descriptor.values_by_number.get(language_enum)
            
            if enum_value:
                return enum_value.name
            else:
                logger.warning(f"Unknown programming language enum value: {language_enum}")
                return "EMPTY"  # Default fallback
                
        except Exception as e:
            logger.error(f"Error converting language enum {language_enum}: {e}")
            # Fallback to hardcoded mapping as last resort
            language_map = {0: "EMPTY", 1: "JAVA", 2: "PYTHON"}
            return language_map.get(language_enum, "EMPTY")

    def _create_response(
        self,
        context: SolutionCreationContext,
        request,
    ):
        # Import at runtime to avoid protobuf version issues
        from app.grpc import hyperion_pb2

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

        return hyperion_pb2.SolutionRepositoryCreatorResponse(
            programming_language=request.programming_language,
            project_type=request.project_type,
            difficulty=request.difficulty,
            points=request.points,
            bonus_points=request.bonus_points,
            constraints=request.constraints,
            title=request.title,
            short_title=request.short_title,
            description=request.description,
            solution_repository=context.solution_repository
            or self._create_empty_repository(),
        )

    def _create_empty_repository(self):
        # Import at runtime to avoid protobuf version issues
        from app.grpc import hyperion_pb2

        return hyperion_pb2.Repository(files=[])

    def _cleanup_workspace(self, context: SolutionCreationContext) -> None:
        """Clean up the temporary workspace directory.

        Args:
            context: The solution creation context
        """
        try:
            if context.workspace_path:
                # Use the workspace manager for proper cleanup
                cleanup_performed = self.workspace_manager.cleanup_workspace(
                    context.workspace_path
                )
                
                if cleanup_performed:
                    logger.info(f"Workspace cleaned up: {context.workspace_path}")
                else:
                    logger.info(f"Workspace preserved at: {context.workspace_path}")
            else:
                logger.warning("No workspace path set in context")

        except Exception as e:
            logger.warning(f"Failed to cleanup workspace: {str(e)}")

    def get_supported_languages(self) -> List[str]:
        return language_registry.get_supported_languages()

    def get_language_info(self, language: str) -> Dict[str, Any]:
        return language_registry.get_handler_info(language) or {}
