from fastapi import APIRouter, Depends

from app.settings import settings
from .models import SolutionRepositoryCreatorRequest, SolutionRepositoryCreatorResponse
from .handler import SolutionRepositoryCreator

router = APIRouter(
    prefix="/create-solution-repository", tags=["create-solution-repository"]
)


def get_solution_repository_creator() -> SolutionRepositoryCreator:
    """Dependency to get solution repository creator instance."""
    return SolutionRepositoryCreator(model_name=settings.MODEL_NAME)


@router.post("/", response_model=SolutionRepositoryCreatorResponse)
async def create_solution_repository(
    request: SolutionRepositoryCreatorRequest,
    creator: SolutionRepositoryCreator = Depends(get_solution_repository_creator),
) -> SolutionRepositoryCreatorResponse:
    """
    Create a solution repository based on boundary conditions and problem statement.

    This endpoint generates a complete working solution for a programming exercise,
    including source code, test files, and build configuration files.
    """
    return await creator.create(request)
