"""
API routes for the consistency checker module.
"""

from fastapi import APIRouter, status

from app.consistency_checker.models import (
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
)
from app.consistency_checker.service import ConsistencyCheckerService

checker_service = ConsistencyCheckerService()

router = APIRouter(
    prefix="/consistency-check",
    tags=["consistency-check"],
    responses={
        404: {"description": "Not found"},
        500: {"description": "Internal server error"},
    },
)


@router.post(
    "/check",
    response_model=ConsistencyCheckResponse,
    status_code=status.HTTP_200_OK,
    description="Check for consistency issues in a programming exercise",
)
async def check_consistency(request: ConsistencyCheckRequest):
    """
    Check a programming exercise for consistency issues between problem statement,
    template repository, and solution repository.

    Returns a list of identified issues and a summary.
    """
    result = await checker_service.check_exercise_consistency(request.exercise)
    return result
