from typing import List, Optional

from pydantic import Field

from ...domain.status.activity_dto import ActivityDTO
from ...domain.status.status_update_dto import StatusUpdateDTO


class IngestionStatusUpdateDTO(StatusUpdateDTO):
    """Status update sent to Artemis during lecture ingestion, including live per-step activities."""

    result: Optional[str] = None
    id: Optional[int] = None
    display_page_numbers: Optional[list[int]] = Field(
        default=None,
        alias="displayPageNumbers",
    )
    # Live per-step progress for the admin ingestion dashboard, mirroring the chat status stream: each
    # activity is a named pipeline step with a RUNNING/FINISHED/FAILED state and, once terminal, its
    # duration. ``activity_seq`` lets the receiver drop out-of-order snapshots. ``started_at`` is the
    # ISO-8601 run start time, so the dashboard can show elapsed time.
    activities: Optional[List[ActivityDTO]] = None
    activity_seq: Optional[int] = Field(alias="activitySeq", default=None)
    started_at: Optional[str] = Field(alias="startedAt", default=None)
