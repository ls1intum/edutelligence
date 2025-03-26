from dataclasses import dataclass
from typing import List, Optional


@dataclass
class LectureUnitRetrievalDTO:
    """Data Transfer Object for retrieving lecture unit details.

    Contains course and lecture information along with summaries and identifiers.
    """

    uuid: str
    course_id: int
    course_name: str
    course_description: str
    course_language: str
    lecture_id: Optional[int]
    lecture_name: Optional[str]
    lecture_unit_id: Optional[int]
    lecture_unit_name: Optional[str]
    lecture_unit_link: Optional[str]
    video_link: Optional[str]
    base_url: str
    lecture_unit_summary: str


@dataclass
class LectureUnitSegmentRetrievalDTO:
    """Data Transfer Object for retrieving a segment of a lecture unit.

    Contains details about the course, lecture, unit, and segment summary along with pagination information.
    """

    uuid: str
    course_id: int
    course_name: str
    course_description: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: str
    page_number: int
    segment_summary: str
    base_url: str


@dataclass
class LectureTranscriptionRetrievalDTO:
    """Data Transfer Object for retrieving lecture transcription details.

    Contains transcription timing, textual content, and associated lecture metadata.
    """

    uuid: str
    course_id: int
    course_name: str
    course_description: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    video_link: str
    language: str
    segment_start_time: float
    segment_end_time: float
    page_number: int
    segment_summary: str
    segment_text: str
    base_url: str


@dataclass
class LectureUnitPageChunkRetrievalDTO:
    """Data Transfer Object for retrieving page chunk details of a lecture unit.

    Includes text content of the page and additional metadata about the course and lecture.
    """

    uuid: str
    course_id: int
    course_name: str
    course_description: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: str
    course_language: str
    page_number: int
    page_text_content: str
    base_url: str


@dataclass
class LectureRetrievalDTO:
    """Data Transfer Object for retrieving complete lecture information.

    Aggregates lecture unit segments, transcriptions, and page chunks.
    """

    lecture_unit_segments: List[LectureUnitSegmentRetrievalDTO]
    lecture_transcriptions: List[LectureTranscriptionRetrievalDTO]
    lecture_unit_page_chunks: List[LectureUnitPageChunkRetrievalDTO]
