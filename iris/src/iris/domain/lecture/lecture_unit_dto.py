from typing import Optional

from pydantic import BaseModel


class LectureUnitDTO(BaseModel):
    """DTO to store all lecture unit information."""

    course_id: int
    course_name: str
    course_description: str
    course_language: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: Optional[str] = ""
    video_link: Optional[str] = ""
    base_url: str
    lecture_unit_summary: Optional[str] = ""
    content_fingerprint: Optional[str] = None
    ingestion_run_id: Optional[str] = None
    expected_chunk_counts_json: Optional[str] = None
    pipeline_version: Optional[int] = None
    quality_score: Optional[float] = None
    quality_flags_json: Optional[str] = None
    # True when every content sub-pipeline structurally skipped this run, which
    # makes it provably safe to reuse the stored unit summary and its vector.
    content_unchanged: bool = False
