from threading import Thread

from fastapi import APIRouter, Depends
from fastapi import status as http_status

from iris.common.logging_config import get_logger, get_request_id, set_request_id
from iris.dependencies import TokenValidator
from iris.domain.search.lecture_search_dto import (
    LectureSearchAskRequestDTO,
    LectureSearchRequestDTO,
    LectureSearchResultDTO,
)
from iris.pipeline.lecture_search_answer_pipeline import LectureSearchAnswerPipeline
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import SearchAnswerCallback

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


def _run_search_ask_worker(dto: LectureSearchAskRequestDTO, request_id: str) -> None:
    """Worker function run in a background thread for the Ask Iris pipeline."""
    set_request_id(request_id)
    callback = SearchAnswerCallback(
        run_id=dto.authentication_token,
        base_url=dto.artemis_base_url,
    )
    try:
        client = VectorDatabase().get_client()
        LectureSearchAnswerPipeline(client)(dto=dto, callback=callback)
    except Exception as e:
        logger.error("Search ask pipeline worker failed", exc_info=e)
        callback.error("Fatal error in search pipeline.", exception=e)


@router.post(
    "/ask",
    status_code=http_status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def lecture_ask(dto: LectureSearchAskRequestDTO) -> dict:
    """
    Answer a student's question using lecture content retrieved via HyDE.

    Returns 202 immediately. Results are pushed asynchronously to Artemis via two
    HTTP callbacks:
      - cited=false: plain answer with [cite-loading:keyword] skeleton markers (~3-4s)
      - cited=true:  answer with full [cite:L:...] inline citation markers (~7-9s)

    :return: {"token": "<authentication_token>"} for the client to subscribe on WebSocket.
    """
    request_id = get_request_id()
    thread = Thread(
        target=_run_search_ask_worker,
        args=(dto, request_id),
    )
    thread.start()
    return {"token": dto.authentication_token}
