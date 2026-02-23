from fastapi import APIRouter, Depends

from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.domain.search.lecture_search_dto import (
    LectureSearchRequestDTO,
    LectureSearchResultDTO,
)
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.vector_database.database import VectorDatabase

router = APIRouter(prefix="/api/v1/search", tags=["search"])
logger = get_logger(__name__)


@router.post("/lectures", dependencies=[Depends(TokenValidator())])
def lecture_search(dto: LectureSearchRequestDTO) -> list[LectureSearchResultDTO]:
    """
    Search for lectures based on a query.

    :return: The search results.
    """
    client = VectorDatabase().get_client()
    return LectureGlobalSearchRetrieval(client).search(dto.query, dto.limit)
