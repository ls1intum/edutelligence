import logging
from typing import Dict, Any, Optional, List
from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc, hyperion_pb2
from app.grpc.models import Repository

from .models import (
    SolutionRepositoryCreatorRequest, 
    SolutionRepositoryCreatorResponse,
    SolutionCreationContext,
    SolutionCreationPhase,
    SolutionCreationStep
)
from .phases import PlanningPhase, TestingPhase, ValidationPhase
from .workspace import TempWorkspaceManager
from .language_handlers import registry as language_registry
from .exceptions import SolutionCreatorException, LanguageHandlerException
from .config import config

logger = logging.getLogger(__name__)


class SolutionRepositoryCreatorServicer(hyperion_pb2_grpc.SolutionRepositoryCreatorServicer):
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
        self.planning_phase = PlanningPhase(model=model)
        self.testing_phase = TestingPhase(model=model)
        self.validation_phase = ValidationPhase(model=model)

    async def CreateSolutionRepository(self, request: hyperion_pb2.SolutionRepositoryCreatorRequest, 
                                     context: Any) -> hyperion_pb2.SolutionRepositoryCreatorResponse:
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
            
            solution_context = self._initialize_context(request_model)
            self._validate_language_support(solution_context)
            
            workspace_path = self.workspace_manager.create_workspace(solution_context)
            solution_context.workspace_path = workspace_path
            
            solution_context = await self._execute_solution_creation(solution_context)
            
            response = self._create_response(solution_context, request_model)
            
            self._cleanup_workspace(solution_context)
            
            logger.info("Solution repository created successfully")
            return response.to_grpc()
            
        except SolutionCreatorException as e:
            logger.error(f"Solution creator error: {str(e)}")
            context.set_code(hyperion_pb2_grpc.grpc.StatusCode.INTERNAL)
            context.set_details(f"Solution creation failed: {str(e)}")
            raise
            
        except Exception as e:
            logger.error(f"Unexpected error creating solution repository: {str(e)}")
            context.set_code(hyperion_pb2_grpc.grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to create solution repository: {str(e)}")
            raise

    def _initialize_context(self, request: SolutionRepositoryCreatorRequest) -> SolutionCreationContext:
        return SolutionCreationContext(
            boundary_conditions=request.boundary_conditions,
            problem_statement=request.problem_statement,
            workspace_path="",  # Will be set after workspace creation
            current_phase=SolutionCreationPhase.PLANNING,
            current_step=SolutionCreationStep.GENERATE_PLAN,
            model=self.model
        )

    def _validate_language_support(self, context: SolutionCreationContext) -> None:
        language = context.boundary_conditions.programming_language
        if not language_registry.is_supported(language):
            supported_languages = language_registry.get_supported_languages()
            raise LanguageHandlerException(
                f"Programming language '{language}' is not supported",
                language=language,
                details={"supported_languages": supported_languages}
            )

    async def _execute_solution_creation(self, context: SolutionCreationContext) -> SolutionCreationContext:
        logger.info("Starting solution creation process")
        
        # Phase 1: Planning & Structure
        context.current_phase = SolutionCreationPhase.PLANNING
        context = await self.planning_phase.execute(context)
        
        # Phase 2: Test Creation
        context.current_phase = SolutionCreationPhase.TESTING
        context = await self.testing_phase.execute(context)
        
        # Phase 3: Validation & Refinement
        context.current_phase = SolutionCreationPhase.VALIDATION
        context = await self.validation_phase.execute(context)
        
        logger.info("Solution creation process completed")
        return context

    def _create_response(self, context: SolutionCreationContext, 
                        request: SolutionRepositoryCreatorRequest) -> SolutionRepositoryCreatorResponse:
        # Determine success based on context
        success = (
            context.solution_repository is not None and
            len(context.fix_attempts) < config.max_iterations
        )
        
        # Create error message if failed
        error_message = None
        if not success:
            if context.solution_repository is None:
                error_message = "Failed to generate solution repository"
            elif len(context.fix_attempts) >= config.max_iterations:
                error_message = f"Maximum iterations ({config.max_iterations}) exceeded"
        
        return SolutionRepositoryCreatorResponse(
            boundary_conditions=request.boundary_conditions,
            problem_statement=request.problem_statement,
            solution_repository=context.solution_repository or self._create_empty_repository(),
            success=success,
            error_message=error_message,
            metadata={
                "phases_completed": context.current_phase,
                "final_step": context.current_step,
                "fix_attempts": len(context.fix_attempts),
                "workspace_path": context.workspace_path
            }
        )

    def _create_empty_repository(self) -> Repository:
        return Repository(files=[])

    def _cleanup_workspace(self, context: SolutionCreationContext) -> None:
        try:
            # Determine if we should cleanup based on success and configuration
            should_cleanup = (
                (context.solution_repository is not None and config.cleanup_on_success) or
                (context.solution_repository is None and config.cleanup_on_failure)
            )
            
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
