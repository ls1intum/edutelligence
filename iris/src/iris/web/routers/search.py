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
from iris.tracing import observe
from iris.vector_database.database import VectorDatabase

router = APIRouter(prefix="/api/v1/search", tags=["search"])
logger = get_logger(__name__)


@router.post(
    "/lectures", dependencies=[Depends(TokenValidator())], response_model_by_alias=True
)
def lecture_search(dto: LectureSearchRequestDTO) -> list[LectureSearchResultDTO]:
    """Search for lectures based on a query.

    The retrieval is traced in Langfuse and logged at INFO ([LectureSearch] ...):
    the query, course filter, and each hit's score + course + unit + snippet, so the
    retrieval behind a real user search is fully visible without the UI. Tracing lives
    on the inner ``_traced_lecture_search`` so the route signature stays clean for
    FastAPI's request-body parsing.
    """
    logger.info(
        "[LectureSearch] request query=%r limit=%s course_ids=%s",
        dto.query,
        dto.limit,
        dto.course_ids,
    )
    return _traced_lecture_search(dto)


@observe(name="Lecture Search", as_type="retriever")
def _traced_lecture_search(
    dto: LectureSearchRequestDTO,
) -> list[LectureSearchResultDTO]:
    client = VectorDatabase().get_client()
    return LectureGlobalSearchRetrieval(client).search(
        dto.query, dto.limit, course_ids=dto.course_ids
    )
