from typing import List, Optional
from dataclasses import dataclass


@dataclass
class LectureUnitRetrievalDTO:
    course_id: int
    course_name: str
    course_description: str
    course_language: str
    lecture_id: Optional[int]
    lecture_name: Optional[str]
    lecture_unit_id: Optional[int]
    lecture_unit_name: Optional[str]
    lecture_unit_link: Optional[str]
    base_url: str
    lecture_unit_summary: str


@dataclass
class LectureUnitSegmentRetrievalDTO:
    course_id: int
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    page_number: int
    segment_summary: str


@dataclass
class LectureTranscriptionRetrievalDTO:
    course_id: int
    course_name: str
    course_description: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: str
    language: str
    segment_start_time: float
    segment_end_time: float
    page_number: int
    segment_summary: str
    segment_text: str


@dataclass
class LectureUnitPageChunkRetrievalDTO:
    course_id: int
    course_name: str
    course_description: str
    lecture_id: int
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: str
    course_language: str
    page_number: int
    page_text_content: str


@dataclass
class LectureRetrievalDTO:
    lecture_units: List[LectureUnitRetrievalDTO]
    lecture_unit_segments: List[LectureUnitSegmentRetrievalDTO]
    lecture_transcriptions: List[LectureTranscriptionRetrievalDTO]
    lecture_unit_page_chunks: List[LectureUnitPageChunkRetrievalDTO]
