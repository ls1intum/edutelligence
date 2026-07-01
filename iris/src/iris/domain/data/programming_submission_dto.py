from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.result_dto import ResultDTO


class ProgrammingSubmissionDTO(BaseModel):
    id: int
    date: Optional[datetime] = None
    repository: Dict[str, str] = Field(alias="repository", default={})
    # The committed (last-submitted-build) version of ONLY the code files the student changed locally.
    # `repository` above is the live working copy; this is what get_feedbacks/latest_result reflect. Used by
    # the local_vs_submitted_diff tool. Empty => no code changed since the submission (iff it was readable).
    submitted_repository: Dict[str, str] = Field(
        alias="submittedRepository", default={}
    )
    # Whether the submitted (committed) repository was actually read. Default False = conservative "unavailable"
    # so a repo-fetch failure is never misreported as "no changes since the submission".
    submitted_repository_available: bool = Field(
        alias="submittedRepositoryAvailable", default=False
    )
    is_practice: bool = Field(alias="isPractice")
    build_failed: bool = Field(alias="buildFailed")
    build_log_entries: List[BuildLogEntryDTO] = Field(
        alias="buildLogEntries", default=[]
    )
    latest_result: Optional[ResultDTO] = Field(alias="latestResult", default=None)
