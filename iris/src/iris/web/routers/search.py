from fastapi import APIRouter, Depends

from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.domain.search.lecture_search_dto import (
    LectureSearchAskRequestDTO,
    LectureSearchAskResponseDTO,
    LectureSearchRequestDTO,
    LectureSearchResultDTO,
)
from iris.pipeline.lecture_search_answer_pipeline import LectureSearchAnswerPipeline
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
    """
    Search for lectures based on a query.

    :return: The search results.
    """
    client = VectorDatabase().get_client()
    return LectureGlobalSearchRetrieval(client).search(dto.query, dto.limit)


@router.post(
    "/ask", dependencies=[Depends(TokenValidator())], response_model_by_alias=True
)
def lecture_ask(dto: LectureSearchAskRequestDTO) -> LectureSearchAskResponseDTO:
    """
    Answer a student's question using lecture content retrieved.

    Retrieves relevant lecture segments using Hypothetical Document Embedding (HyDE)
    and generates a concise answer grounded in the retrieved content.

    :return: An answer with clickable source references.
    """
    client = VectorDatabase().get_client()
    return LectureSearchAnswerPipeline(client)(query=dto.query, limit=dto.limit)
