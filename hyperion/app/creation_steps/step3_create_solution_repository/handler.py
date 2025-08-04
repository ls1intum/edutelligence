"""Handler for Step 3: Create Solution Repository."""

import logging
from uuid import uuid4
from typing import List

from app.models import init_hyperion_chat_model

from app.creation_steps.models import Metadata, Repository
from app.creation_steps.step3_create_solution_repository.models import (
    SolutionRepositoryCreatorRequest,
    SolutionRepositoryCreatorResponse,
    SolutionCreationContext,
)
from app.creation_steps.step3_create_solution_repository.code_generator import (
    CodeGenerator,
)
from app.creation_steps.step3_create_solution_repository.language_handlers import (
    registry as language_registry,
)
from app.creation_steps.step3_create_solution_repository.exceptions import (
    SolutionCreatorException,
    LanguageHandlerException,
)
from app.creation_steps.workspace.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class SolutionRepositoryCreator:
    """Handler for creating solution repositories."""

    def __init__(self, model_name: str):
        self.model = init_hyperion_chat_model(model_name)
        self.code_generator: CodeGenerator = CodeGenerator(model=self.model)
        self.workspace_manager: WorkspaceManager = WorkspaceManager()

    async def create(
        self, request: SolutionRepositoryCreatorRequest
    ) -> SolutionRepositoryCreatorResponse:
        """
        Create a solution repository based on boundary conditions and problem statement.

        Args:
            request: Contains boundary conditions and problem statement

        Returns:
            SolutionRepositoryCreatorResponse: Contains the generated solution repository
        """
        trace_id: str = str(uuid4())
        logger.info(f"Creating solution repository with trace_id: {trace_id}")

        try:
            context: SolutionCreationContext = SolutionCreationContext(
                boundary_conditions=request.boundary_conditions,
                problem_statement=request.problem_statement,
                workspace_path="",  # Will be set after workspace creation
                model=self.model,
            )

            # Validate language support
            language_str: str = request.boundary_conditions.programming_language.value
            if not language_registry.is_supported(language_str):
                supported_languages: List[str] = (
                    language_registry.get_supported_languages()
                )
                raise LanguageHandlerException(
                    f"Programming language '{language_str}' is not supported",
                    language=language_str,
                    details={"supported_languages": supported_languages},
                )

            context.workspace_path = self.workspace_manager.create_workspace(
                prefix="solution_creation_"
            )

            context: SolutionCreationContext = await self.code_generator.execute(
                context
            )

            # Clean up workspace
            if context.workspace_path and self.workspace_manager:
                try:
                    self.workspace_manager.cleanup_workspace(context.workspace_path)
                    logger.debug(f"Cleaned up workspace: {context.workspace_path}")
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup workspace {context.workspace_path}: {e}"
                    )

            logger.info("Solution repository created successfully")

            return SolutionRepositoryCreatorResponse(
                repository=context.solution_repository or Repository(files=[]),
                metadata=Metadata(trace_id=str(trace_id)),
            )

        except SolutionCreatorException as e:
            logger.error(f"Solution creator error: {str(e)}")
            raise e

        except Exception as e:
            logger.error(f"Unexpected error creating solution repository: {str(e)}")
            raise SolutionCreatorException(
                f"Failed to create solution repository: {str(e)}"
            ) from e
