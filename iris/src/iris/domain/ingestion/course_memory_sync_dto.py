from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field, model_validator

from iris.common.artemis_instance import canonical_artemis_base_url
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO
from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO


class CourseMemorySyncThreadDTO(BaseModel):
    """One thread that may have a Course Memory entry, as Artemis sees it now."""

    model_config = ConfigDict(populate_by_name=True)

    post_id: int = Field(alias="postId")
    # The thread's current Course Memory version in Artemis. An entry written with an
    # older version missed an update that Artemis already dispatched.
    version: int = Field(alias="version", ge=1)
    # Whether the thread may be stored right now: readable channel, Iris enabled, root
    # post exists. A thread that is not eligible must not keep a live entry. Artemis
    # leaves false out of the payload, so a missing value means not eligible.
    eligible: bool = False


class _SyncDTO(PipelineExecutionDTO):
    """Fields shared by both sync requests."""

    settings: PipelineExecutionSettingsDTO
    # When Artemis read the state it reports. Objects Iris wrote after this moment (with
    # a safety margin for clock skew) are left alone: they can describe threads that
    # changed after the snapshot.
    snapshot_at: datetime = Field(alias="snapshotAt")

    @model_validator(mode="after")
    def _require_artemis_instance(self):
        canonical_artemis_base_url(self.settings.artemis_base_url)
        return self

    @property
    def base_url(self) -> str:
        """Canonical URL of the sending Artemis instance."""
        return canonical_artemis_base_url(self.settings.artemis_base_url)


class CourseMemoryCourseSyncDTO(_SyncDTO):
    """The complete list of threads of one course that may have an entry.

    Complete is essential: an entry whose thread is not listed counts as belonging to a
    deleted thread and is retracted.
    """

    course_id: int = Field(alias="courseId")
    threads: List[CourseMemorySyncThreadDTO] = Field(default_factory=list)


class CourseMemoryInstanceSyncDTO(_SyncDTO):
    """Every course of the Artemis instance that still exists.

    Entries of courses not in the list belong to deleted courses and are retracted.
    """

    course_ids: List[int] = Field(alias="courseIds")
