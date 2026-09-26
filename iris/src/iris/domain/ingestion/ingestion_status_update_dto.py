from typing import Optional

from pydantic import Field

from ...domain.status.status_update_dto import StatusUpdateDTO


class IngestionStatusUpdateDTO(StatusUpdateDTO):
    """Status update payload for a lecture ingestion run, including stage-level liveness."""

    result: Optional[str] = None
    id: Optional[int] = None
    display_page_numbers: Optional[list[int]] = Field(
        default=None,
        alias="displayPageNumbers",
    )
    # Stage-level liveness for the Artemis stage ledger. Deliberately sticky
    # (not transient): every later heartbeat re-reports the last known stage and
    # progress, so Artemis can distinguish a run that is alive but stalled (the
    # progress counter stops moving) from one that is merely slow (it keeps
    # moving through a long stage). All three are optional so older Artemis
    # versions simply ignore them.
    stage_name: Optional[str] = Field(default=None, alias="stageName")
    stage_progress: Optional[int] = Field(default=None, alias="stageProgress")
    stage_total: Optional[int] = Field(default=None, alias="stageTotal")
