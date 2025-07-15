from fastapi import APIRouter, Depends
import logging

from app.settings import settings

from .consistency_check.handler import ConsistencyCheck
from .consistency_check.models import ConsistencyCheckRequest, ConsistencyCheckResponse
from .problem_statement_rewrite.handler import ProblemStatementRewrite
from .problem_statement_rewrite.models import (
    RewriteProblemStatementRequest,
    RewriteProblemStatementResponse,
)

router = APIRouter(prefix="/review-and-refine", tags=["review-and-refine"])
logger = logging.getLogger(__name__)


def get_consistency_checker() -> ConsistencyCheck:
    """Dependency to get the consistency checker instance."""
    return ConsistencyCheck(settings.MODEL_NAME)


def get_problem_statement_rewriter() -> ProblemStatementRewrite:
    """Dependency to get the problem statement rewriter instance."""
    return ProblemStatementRewrite(settings.MODEL_NAME)


@router.post("/consistency-check", response_model=ConsistencyCheckResponse)
async def consistency_check(
    request: ConsistencyCheckRequest,
    consistency_checker: ConsistencyCheck = Depends(get_consistency_checker),
) -> ConsistencyCheckResponse:
    """
    Check consistency between problem statement, solution, template, and test repositories.

    Analyzes the provided exercise artifacts and identifies potential
    consistency issues across different artifact types.
    """
    return consistency_checker.check(request)


@router.post(
    "/problem-statement-rewrite", response_model=RewriteProblemStatementResponse
)
async def problem_statement_rewrite(
    request: RewriteProblemStatementRequest,
    problem_statement_rewriter: ProblemStatementRewrite = Depends(
        get_problem_statement_rewriter
    ),
) -> RewriteProblemStatementResponse:
    """
    Rewrite and improve a problem statement.

    Takes a problem statement text and returns an improved version
    with better clarity, structure, and pedagogical value.
    """
    return problem_statement_rewriter.rewrite(request)
