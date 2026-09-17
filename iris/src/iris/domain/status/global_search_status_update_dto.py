from typing import List, Optional

from pydantic import Field

from iris.domain.search.global_search_dto import (
    EntitySourceDTO,
    LectureSearchResultDTO,
)
from iris.domain.status.status_update_dto import StatusUpdateDTO


class GlobalSearchStatusUpdateDTO(StatusUpdateDTO):
    """Status update DTO for the global search pipeline.

    Sent to Artemis via webhook at two points:
      1. Immediately after intent classification — answer=None, sources=[] (thinking)
      2. After the pipeline finishes — answer=str|None, sources=[...]
    """

    result: Optional[str] = None
    answer: Optional[str] = None
    # Streaming draft of the answer while the LLM generates (RUNNING updates
    # from the PartialResultSender); the terminal update carries the
    # authoritative sanitized answer. Mirrors the chat DTO's fields.
    partial_result: Optional[str] = Field(alias="partialResult", default=None)
    partial_seq: Optional[int] = Field(alias="partialSeq", default=None)
    sources: List[LectureSearchResultDTO] = Field(default_factory=list)
    # Additive (wire freeze rules): old Artemis ignores the unknown field.
    entity_sources: List[EntitySourceDTO] = Field(
        default_factory=list, alias="entitySources"
    )
