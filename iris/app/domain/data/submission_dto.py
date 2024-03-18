from typing import List, Dict, Optional

from pydantic import BaseModel, Field

from datetime import datetime
from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.result_dto import ResultDTO


class SubmissionDTO(BaseModel):
    id: int
    date: Optional[datetime] = None
    repository: Dict[str, str]
    is_practice: bool = Field(alias="isPractice")
    build_failed: bool = Field(alias="buildFailed")
    build_log_entries: List[BuildLogEntryDTO] = Field(
        alias="buildLogEntries", default=[]
    )
    latest_result: Optional[ResultDTO] = Field(alias="latestResult", default=None)
