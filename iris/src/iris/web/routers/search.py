from fastapi import APIRouter

from iris.common.logging_config import get_logger
from iris.dependencies import AuthorizedKey, require_base_url
from iris.domain.search.global_search_dto import (
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


@router.post("/lectures", response_model_by_alias=True)
def lecture_search(
    api_key: AuthorizedKey, dto: LectureSearchRequestDTO
) -> list[LectureSearchResultDTO]:
    """Search for lectures based on a query.

    The retrieval is traced in Langfuse and logged at INFO ([LectureSearch] ...):
    the query, course filter, and each hit's score + course + unit + snippet, so the
    retrieval behind a real user search is fully visible without the UI. Tracing lives
    on the inner ``_traced_lecture_search`` so the route signature stays clean for
    FastAPI's request-body parsing.
    """
    require_base_url(api_key, dto.artemis_base_url)
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
        dto.query,
        dto.limit,
        base_url=dto.artemis_base_url,
        course_ids=dto.course_ids,
        exclude_course_ids=dto.exclude_course_ids,
        access_context=dto.access_context,
    )
