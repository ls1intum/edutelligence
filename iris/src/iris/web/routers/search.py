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


@router.post(
    "/lectures", dependencies=[Depends(TokenValidator())], response_model_by_alias=True
)
def lecture_search(dto: LectureSearchRequestDTO) -> list[LectureSearchResultDTO]:
    """Search for lectures based on a query."""
    client = VectorDatabase().get_client()
    # search() returns scored tuples (float, dto) for pipeline use — strip scores for the HTTP response
    return [
        result
        for _, result in LectureGlobalSearchRetrieval(client).search(
            dto.query,
            dto.limit,
            course_ids=dto.course_ids,
            access_context=dto.access_context,
        )
    ]
