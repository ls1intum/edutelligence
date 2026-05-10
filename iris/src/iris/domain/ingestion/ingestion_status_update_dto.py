from typing import Optional

from pydantic import Field

from ...domain.status.status_update_dto import StatusUpdateDTO


class IngestionStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    id: Optional[int] = None
    # Snake-case wire key per spec; Jackson side uses @JsonProperty("error_code").
    # Scoped to ingestion only so non-ingestion pipelines don't emit it.
    error_code: Optional[str] = Field(default=None, alias="error_code")
