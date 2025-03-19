from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.result_dto import ResultDTO


class ProgrammingSubmissionDTO(BaseModel):
    id: int
    date: Optional[datetime] = None
    repository: Dict[str, str] = Field(alias="repository", default={})
    is_practice: bool = Field(alias="isPractice")
    build_failed: bool = Field(alias="buildFailed")
    build_log_entries: List[BuildLogEntryDTO] = Field(
        alias="buildLogEntries", default=[]
    )
    latest_result: Optional[ResultDTO] = Field(
        alias="latestResult", default=None
    )
