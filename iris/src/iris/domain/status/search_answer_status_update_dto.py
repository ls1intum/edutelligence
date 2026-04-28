from typing import List

from pydantic import BaseModel

from iris.domain.search.lecture_search_dto import LectureSearchResultDTO


class SearchAnswerStatusUpdateDTO(BaseModel):
    """Callback body sent to Artemis twice during Ask Iris processing.

    First push (cited=False): plain answer with [cite-loading:keyword] skeleton markers.
    Second push (cited=True): answer with full [cite:L:...] inline citation markers.
    Sources are identical on both pushes so Artemis can render cards immediately.
    """

    cited: bool
    answer: str
    sources: List[LectureSearchResultDTO]
