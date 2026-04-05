"""Tests for VideoTranscriptionPipelineExecutionDto deserialization."""

import pytest

from iris.domain.transcription.video_transcription_execution_dto import (
    VideoSourceType,
    VideoTranscriptionPipelineExecutionDto,
)


def _base_payload(**overrides) -> dict:
    """Build a minimal valid Artemis-style JSON payload."""
    payload = {
        "videoUrl": "https://example.com/video.mp4",
        "lectureUnitId": 1,
        "lectureId": 2,
        "courseId": 3,
        "courseName": "Test Course",
        "lectureName": "Test Lecture",
        "lectureUnitName": "Test Unit",
    }
    payload.update(overrides)
    return payload


class TestVideoSourceTypeDeserialization:
    """Tests for VideoSourceType deserialization from Artemis JSON."""
    def test_youtube_source_type(self):
        dto = VideoTranscriptionPipelineExecutionDto(
            **_base_payload(videoSourceType="YOUTUBE")
        )
        assert dto.video_source_type == VideoSourceType.YOUTUBE

    def test_tum_live_source_type(self):
        dto = VideoTranscriptionPipelineExecutionDto(
            **_base_payload(videoSourceType="TUM_LIVE")
        )
        assert dto.video_source_type == VideoSourceType.TUM_LIVE

    def test_missing_source_type_defaults_to_tum_live(self):
        dto = VideoTranscriptionPipelineExecutionDto(**_base_payload())
        assert dto.video_source_type == VideoSourceType.TUM_LIVE

    def test_invalid_source_type_raises(self):
        with pytest.raises(ValueError):
            VideoTranscriptionPipelineExecutionDto(
                **_base_payload(videoSourceType="INVALID")
            )


class TestFieldAliases:
    """Tests for Pydantic camelCase alias mapping."""
    def test_camel_case_aliases(self):
        dto = VideoTranscriptionPipelineExecutionDto(
            **_base_payload(
                videoSourceType="YOUTUBE",
                videoUrl="https://youtube.com/watch?v=abc",
                lectureUnitId=10,
                lectureId=20,
                courseId=30,
                courseName="CS 101",
                lectureName="Intro",
                lectureUnitName="Part 1",
            )
        )
        assert dto.video_url == "https://youtube.com/watch?v=abc"
        assert dto.lecture_unit_id == 10
        assert dto.lecture_id == 20
        assert dto.course_id == 30
        assert dto.course_name == "CS 101"
        assert dto.lecture_name == "Intro"
        assert dto.lecture_unit_name == "Part 1"
        assert dto.video_source_type == VideoSourceType.YOUTUBE

    def test_settings_defaults_to_none(self):
        dto = VideoTranscriptionPipelineExecutionDto(**_base_payload())
        assert dto.settings is None

    def test_initial_stages_defaults_to_none(self):
        dto = VideoTranscriptionPipelineExecutionDto(**_base_payload())
        assert dto.initial_stages is None


class TestVideoSourceTypeEnum:
    def test_enum_values(self):
        assert VideoSourceType.TUM_LIVE.value == "TUM_LIVE"
        assert VideoSourceType.YOUTUBE.value == "YOUTUBE"

    def test_enum_is_str(self):
        assert isinstance(VideoSourceType.TUM_LIVE, str)
        assert isinstance(VideoSourceType.YOUTUBE, str)

    def test_enum_string_comparison(self):
        assert VideoSourceType.YOUTUBE == "YOUTUBE"
        assert VideoSourceType.TUM_LIVE == "TUM_LIVE"
