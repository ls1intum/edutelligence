"""DTOs for the per-course ingestion census."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class IngestionCensusUnitDTO(BaseModel):
    """Aggregated index state for one lecture unit."""

    model_config = ConfigDict(populate_by_name=True)

    lecture_id: Optional[int] = Field(default=None, alias="lectureId")
    lecture_unit_id: int = Field(alias="lectureUnitId")
    content_fingerprint: Optional[str] = Field(default=None, alias="contentFingerprint")
    unit_row_count: int = Field(default=0, alias="unitRowCount")
    expected_chunk_count: Optional[int] = Field(
        default=None, alias="expectedChunkCount"
    )
    pipeline_version: Optional[int] = Field(default=None, alias="pipelineVersion")
    quality_score: Optional[float] = Field(default=None, alias="qualityScore")
    chunk_count: int = Field(default=0, alias="chunkCount")
    chunk_page_min: Optional[int] = Field(default=None, alias="chunkPageMin")
    chunk_page_max: Optional[int] = Field(default=None, alias="chunkPageMax")
    chunk_version_min: Optional[int] = Field(default=None, alias="chunkVersionMin")
    chunk_version_max: Optional[int] = Field(default=None, alias="chunkVersionMax")
    transcription_count: int = Field(default=0, alias="transcriptionCount")
    segment_count: int = Field(default=0, alias="segmentCount")
    segment_page_min: Optional[int] = Field(default=None, alias="segmentPageMin")
    segment_page_max: Optional[int] = Field(default=None, alias="segmentPageMax")


class IngestionCensusDTO(BaseModel):
    """Index state for every lecture unit of one course.

    Units appear when ANY collection holds rows for them, so orphaned content
    whose unit row is gone is still visible to the caller.
    """

    model_config = ConfigDict(populate_by_name=True)

    course_id: int = Field(alias="courseId")
    current_pipeline_version: Optional[int] = Field(
        default=None, alias="currentPipelineVersion"
    )
    units: list[IngestionCensusUnitDTO] = Field(default_factory=list)
