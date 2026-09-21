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
    # Short stage name ("searching", "generating") sent alongside a thinking update with no
    # partial_result yet, so the client can show what is actually happening instead of one
    # static "thinking" message for the whole wait. Additive (wire freeze rules): old Artemis
    # ignores the unknown field and falls back to its own generic message.
    stage: Optional[str] = None
    # Distinct course names found so far, in ranked order — empty before retrieval finishes,
    # populated once the "generating" stage fires, so the client can say what it actually
    # found ("Course A, Course B +2 others") instead of a generic "generating" message.
    stage_sources: List[str] = Field(default_factory=list, alias="stageSources")
    # For marker 1..N (in the citation numbering the terminal answer actually uses), which
    # of `sources`/`entity_sources` that marker resolves into — the two arrays are only
    # ordered relative to their OWN type, so a client cannot otherwise tell which array a
    # given marker number belongs to whenever citations interleave between the two types.
    # Additive (wire freeze rules): old Artemis ignores the unknown field, and old Pyris
    # never populates it, so a client seeing it empty just keeps its own prior assumption.
    citation_source_types: List[str] = Field(
        default_factory=list, alias="citationSourceTypes"
    )
